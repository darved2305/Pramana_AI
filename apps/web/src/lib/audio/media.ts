"use client";

/**
 * Live voice turn for one pending question, over the core's media WebSocket
 * (`WS /v1/investigations/{id}/questions/{qid}/media`, protocol in
 * services/core/src/pramana_core/voice/media.py).
 *
 * The microphone is captured by an AudioWorklet (public/worklets/pcm16-capture.js) as 16 kHz
 * mono PCM16 in 1,024-byte frames and streamed as binary messages. The participant token is
 * sent in the first message, never in the URL, so it does not end up in access logs.
 *
 * Barge-in: if the participant starts speaking while the question is playing, playback
 * stops (the server reports `speech_start`).
 */

export type MediaState =
  | "connecting"
  | "ready"
  | "speaking"
  | "listening"
  | "processing"
  | "answered"
  | "closed"
  | "error";

export interface MediaReady {
  question_id: string;
  participant_id: string;
  text: string;
  language: string;
  outcomes: string[];
  model_confirmed: boolean;
}

export interface MediaError {
  code: string;
  message: string;
  status: number;
  fatal: boolean;
}

export interface MediaTranscript {
  text: string;
  detected_language: string | null;
  provider_latency_ms: number | null;
}

export interface MediaHandlers {
  onState?: (s: MediaState) => void;
  onReady?: (r: MediaReady) => void;
  onTranscript?: (t: MediaTranscript) => void;
  onEmptyTranscript?: () => void;
  /** The answer was recorded: `result` is the core's AnswerResult. */
  onAnswer?: (result: unknown) => void;
  onError?: (e: MediaError) => void;
  onLevel?: (rms: number) => void;
  /** Socket closed; `code` follows the server's close codes (1000 normal, 4408 silent, 4409 already answered...). */
  onClose?: (code: number) => void;
  /** Nothing was heard for a while: the question is being asked once more. */
  onReprompt?: (text: string) => void;
  /** The server's call runtime changed state (ASKING, LISTENING, EXTRACTING, ENDED...). */
  onCallState?: (state: string) => void;
  /** Call mode: the consent line to show (and play) before any question. */
  onConsentRequest?: (text: string, language: string) => void;
  /** Call mode: the question being asked was answered elsewhere or withdrawn. */
  onQuestionWithdrawn?: (questionId: string) => void;
  /** Call mode: the call is over (declined, nothing more to ask, silent...). */
  onCallEnd?: (reason: string) => void;
}

export interface MediaOptions {
  /** Same-origin prefix that Next.js rewrites to the core. */
  basePath?: string;
  playQuestion?: boolean;
  workletUrl?: string;
  /** Call mode: one socket for this participant's whole call (ring, consent, every question),
   * `WS /v1/investigations/{id}/participants/{pid}/call` (services/core/.../voice/call.py). */
  callParticipantId?: string;
}

/** ws(s)://<this origin><basePath>/v1/investigations/{id}/participants/{pid}/call */
export function callUrl(investigationId: string, participantId: string, basePath = "/api/core"): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const path = `${basePath}/v1/investigations/${encodeURIComponent(investigationId)}/participants/${encodeURIComponent(participantId)}/call`;
  return `${proto}//${window.location.host}${path}`;
}

/** ws(s)://<this origin><basePath>/v1/investigations/{id}/questions/{qid}/media */
export function mediaUrl(investigationId: string, questionId: string, basePath = "/api/core"): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const path = `${basePath}/v1/investigations/${encodeURIComponent(investigationId)}/questions/${encodeURIComponent(questionId)}/media`;
  return `${proto}//${window.location.host}${path}`;
}

export class QuestionMediaSession {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private mic: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private tts: { utt: number; bytes: number; chunks: ArrayBuffer[] } | null = null;
  private playing: AudioBufferSourceNode | null = null;
  /** Streamed question audio (`format: pcm_s16le`): pieces are scheduled back to back as they arrive. */
  private stream: { utt: number; rate: number; cursor: number; sources: AudioBufferSourceNode[]; ended: boolean; carry: Uint8Array | null } | null = null;
  private state: MediaState = "connecting";

  constructor(
    private readonly investigationId: string,
    private readonly questionId: string,
    private readonly token: string,
    private readonly handlers: MediaHandlers = {},
    private readonly options: MediaOptions = {},
  ) {}

  get current(): MediaState {
    return this.state;
  }

  /** Open the socket and authenticate. Resolves when the server sends `ready` (call mode:
   * when the call starts `ringing`; questions then arrive through `onReady`). */
  connect(): Promise<MediaReady> {
    const callPid = this.options.callParticipantId;
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(
        callPid
          ? callUrl(this.investigationId, callPid, this.options.basePath)
          : mediaUrl(this.investigationId, this.questionId, this.options.basePath),
      );
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      let settled = false;
      ws.onopen = () => {
        const play = this.options.playQuestion ?? true;
        ws.send(JSON.stringify(callPid ? { type: "start", token: this.token, play } : { type: "start", token: this.token, play_question: play }));
      };
      ws.onmessage = (ev) => {
        if (typeof ev.data !== "string") {
          this.onAudio(ev.data as ArrayBuffer);
          return;
        }
        const msg = JSON.parse(ev.data) as { type: string } & Record<string, unknown>;
        if ((callPid ? msg.type === "ringing" : msg.type === "ready") && !settled) {
          settled = true;
          resolve(msg as unknown as MediaReady);
        }
        if (msg.type === "error" && msg.fatal && !settled) {
          settled = true;
          reject(msg as unknown as MediaError);
        }
        this.onControl(msg);
      };
      ws.onerror = () => {
        if (!settled) {
          settled = true;
          reject({ code: "MEDIA_CONNECTION_FAILED", message: "could not connect", status: 0, fatal: true });
        }
      };
      ws.onclose = (ev) => {
        this.stopMic();
        this.stopPlayback();
        if (this.state !== "answered" && this.state !== "error") this.setState("closed");
        this.handlers.onClose?.(ev.code);
        if (!settled) {
          settled = true;
          reject({ code: "MEDIA_CLOSED", message: `closed (${ev.code})`, status: 0, fatal: true });
        }
      };
    });
  }

  /** Start streaming the microphone. Call from a user gesture (autoplay and mic policies). */
  async startMic(): Promise<void> {
    if (this.node) return;
    this.mic = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const ctx = this.audioContext();
    await ctx.audioWorklet.addModule(this.options.workletUrl ?? "/worklets/pcm16-capture.js");
    const src = ctx.createMediaStreamSource(this.mic);
    const node = new AudioWorkletNode(ctx, "pcm16-capture", { numberOfInputs: 1, numberOfOutputs: 0 });
    node.port.onmessage = (e: MessageEvent) => {
      if (e.data instanceof ArrayBuffer) {
        if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(e.data);
      } else if (e.data?.type === "level") {
        this.handlers.onLevel?.(e.data.rms as number);
      }
    };
    src.connect(node);
    this.node = node;
    this.setState("listening");
  }

  /** End of the answer (push-to-talk release): flush the last partial frame and commit. */
  commit(): void {
    this.node?.port.postMessage({ type: "flush" });
    // Let the flushed frame reach the socket before the commit.
    setTimeout(() => this.sendControl({ type: "commit" }), 30);
    this.setState("processing");
  }

  /** Answer by tapping one of the question's outcomes (no speech). */
  tapAnswer(outcome: string): void {
    this.sendControl({ type: "tap_answer", outcome });
  }

  /** Call mode: answer the ring. */
  accept(): void {
    this.sendControl({ type: "accept" });
  }

  /** Call mode: reject the ring. */
  decline(): void {
    this.sendControl({ type: "decline" });
  }

  /** Call mode: the participant's consent. Anything but "yes" ends the call. */
  consent(answer: "yes" | "no" | "later"): void {
    this.sendControl({ type: "consent", answer });
  }

  /** Call mode: stop the microphone after an answer; the call stays open for the next question. */
  endTurn(): void {
    this.stopMic();
    this.levelReset();
  }

  /** Hang up without answering. */
  stop(): void {
    this.sendControl({ type: "stop" });
    this.stopMic();
    this.stopPlayback();
  }

  close(): void {
    this.stopMic();
    this.stopPlayback();
    this.ws?.close();
    this.ctx?.close().catch(() => {});
    this.ctx = null;
  }

  // -- internals ------------------------------------------------------------------------------

  private audioContext(): AudioContext {
    if (!this.ctx) this.ctx = new AudioContext();
    return this.ctx;
  }

  private sendControl(msg: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private setState(s: MediaState): void {
    this.state = s;
    this.handlers.onState?.(s);
  }

  private onControl(msg: { type: string } & Record<string, unknown>): void {
    switch (msg.type) {
      case "ready":
        this.setState("ready");
        this.handlers.onReady?.(msg as unknown as MediaReady);
        break;
      case "tts_start":
        if (msg.format === "pcm_s16le") {
          this.stopPlayback();
          this.tts = null;
          this.stream = { utt: Number(msg.utt_id), rate: Number(msg.sample_rate) || 24000, cursor: 0, sources: [], ended: false, carry: null };
          this.setState("speaking");
        } else {
          this.tts = { utt: Number(msg.utt_id), bytes: Number(msg.bytes), chunks: [] };
        }
        break;
      case "tts_end":
        if (this.stream && this.stream.utt === Number(msg.utt_id)) {
          this.stream.ended = true;
          if (!this.stream.sources.length) this.finishStream();
        } else if (this.tts && this.tts.utt === Number(msg.utt_id)) {
          void this.play(this.tts.chunks);
        }
        this.tts = null;
        break;
      case "speech_start":
        this.stopPlayback(); // barge-in
        this.setState("listening");
        break;
      case "processing":
        this.setState("processing");
        break;
      case "transcript":
        this.handlers.onTranscript?.(msg as unknown as MediaTranscript);
        break;
      case "empty_transcript":
        this.setState(this.node ? "listening" : "ready");
        this.handlers.onEmptyTranscript?.();
        break;
      case "answer":
        this.setState("answered");
        this.handlers.onAnswer?.(msg.result);
        break;
      case "error":
        if (msg.fatal) this.setState("error");
        this.handlers.onError?.(msg as unknown as MediaError);
        break;
      case "stop_playback":
        this.stopPlayback();
        break;
      case "reprompt":
        this.handlers.onReprompt?.(String(msg.text ?? ""));
        break;
      case "call_state":
        this.handlers.onCallState?.(String(msg.state));
        break;
      case "consent_request":
        this.handlers.onConsentRequest?.(String(msg.text ?? ""), String(msg.language ?? ""));
        break;
      case "question_withdrawn":
        this.stopMic();
        this.handlers.onQuestionWithdrawn?.(String(msg.question_id ?? ""));
        break;
      case "call_end":
        this.handlers.onCallEnd?.(String(msg.reason ?? ""));
        break;
    }
  }

  private onAudio(chunk: ArrayBuffer): void {
    if (this.stream) this.schedule(chunk);
    else this.tts?.chunks.push(chunk);
  }

  /** Play one streamed PCM16 piece right after the previous one (gapless). */
  private schedule(chunk: ArrayBuffer): void {
    const st = this.stream;
    if (!st) return;
    let bytes = new Uint8Array(chunk);
    if (st.carry) {
      const joined = new Uint8Array(st.carry.length + bytes.length);
      joined.set(st.carry);
      joined.set(bytes, st.carry.length);
      bytes = joined;
      st.carry = null;
    }
    if (bytes.length % 2) {
      st.carry = bytes.slice(bytes.length - 1);
      bytes = bytes.slice(0, bytes.length - 1);
    }
    if (!bytes.length) return;
    const ctx = this.audioContext();
    const samples = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.length / 2);
    const buf = ctx.createBuffer(1, samples.length, st.rate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < samples.length; i++) ch[i] = samples[i] / 32768;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.05, st.cursor);
    st.cursor = at + buf.duration;
    st.sources.push(src);
    src.onended = () => {
      if (this.stream !== st) return;
      st.sources = st.sources.filter((x) => x !== src);
      if (st.ended && !st.sources.length) this.finishStream();
    };
    src.start(at);
  }

  private finishStream(): void {
    this.stream = null;
    this.sendControl({ type: "playback_done" });
    if (this.state === "speaking") this.setState(this.node ? "listening" : "ready");
  }

  private async play(chunks: ArrayBuffer[]): Promise<void> {
    const total = chunks.reduce((n, c) => n + c.byteLength, 0);
    const wav = new Uint8Array(total);
    let off = 0;
    for (const c of chunks) {
      wav.set(new Uint8Array(c), off);
      off += c.byteLength;
    }
    const ctx = this.audioContext();
    try {
      const buf = await ctx.decodeAudioData(wav.buffer);
      this.stopPlayback();
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(ctx.destination);
      src.onended = () => {
        if (this.playing === src) {
          this.playing = null;
          this.sendControl({ type: "playback_done" });
          if (this.state === "speaking") this.setState(this.node ? "listening" : "ready");
        }
      };
      this.playing = src;
      this.setState("speaking");
      src.start();
    } catch {
      this.handlers.onError?.({ code: "MEDIA_PLAYBACK_FAILED", message: "could not play the question", status: 0, fatal: false });
    }
  }

  private stopPlayback(): void {
    const st = this.stream;
    this.stream = null;
    for (const src of st?.sources ?? []) {
      try {
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    const p = this.playing;
    this.playing = null;
    if (p) {
      try {
        p.stop();
      } catch {
        /* already stopped */
      }
    }
  }

  private levelReset(): void {
    this.handlers.onLevel?.(0);
  }

  private stopMic(): void {
    this.node?.disconnect();
    this.node = null;
    this.mic?.getTracks().forEach((t) => t.stop());
    this.mic = null;
  }
}
