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
  /** Socket closed; `code` follows the server's close codes (1000 normal, 4409 already answered...). */
  onClose?: (code: number) => void;
}

export interface MediaOptions {
  /** Same-origin prefix that Next.js rewrites to the core. */
  basePath?: string;
  playQuestion?: boolean;
  workletUrl?: string;
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

  /** Open the socket and authenticate. Resolves when the server sends `ready`. */
  connect(): Promise<MediaReady> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(mediaUrl(this.investigationId, this.questionId, this.options.basePath));
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      let settled = false;
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "start", token: this.token, play_question: this.options.playQuestion ?? true }));
      };
      ws.onmessage = (ev) => {
        if (typeof ev.data !== "string") {
          this.onAudio(ev.data as ArrayBuffer);
          return;
        }
        const msg = JSON.parse(ev.data) as { type: string } & Record<string, unknown>;
        if (msg.type === "ready" && !settled) {
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
        this.tts = { utt: Number(msg.utt_id), bytes: Number(msg.bytes), chunks: [] };
        break;
      case "tts_end":
        if (this.tts && this.tts.utt === Number(msg.utt_id)) void this.play(this.tts.chunks);
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
    }
  }

  private onAudio(chunk: ArrayBuffer): void {
    this.tts?.chunks.push(chunk);
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

  private stopMic(): void {
    this.node?.disconnect();
    this.node = null;
    this.mic?.getTracks().forEach((t) => t.stop());
    this.mic = null;
  }
}
