"use client";

import { playWavStream, type WavStreamPlayback } from "@/lib/audio/wav-stream";
import { PREVIEW_ENABLED } from "@/lib/store/local";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { Wordmark } from "@/components/brand/Wordmark";
import { VoiceField } from "@/components/voice/VoiceField";
import { DeviceCheck } from "@/components/join/DeviceCheck";
import { IconMic, IconPlay } from "@/components/ui/icons";
import { sim } from "@/lib/api/sim";
import { ApiError, describeError } from "@/lib/api/http";
import { decodeJoin, type JoinPayload } from "@/lib/join";
import { participantApi } from "@/lib/api/participant";
import { startRecording, type Recording } from "@/lib/audio/recorder";
import { QuestionMediaSession, type MediaReady } from "@/lib/audio/media";
import type { AnswerResult, Approval, Extraction, InvestigationState, ParticipantView } from "@/lib/api/types";
import { outcomeWord } from "@/lib/data/derive";

/** What the participant is told was understood. A location check is a reading, not an outcome. */
function heardAs(x: Extraction): string {
  const reading = x.evidence?.find((e) => e.startsWith("reading:"));
  if (reading !== undefined) {
    const value = reading.slice("reading:".length);
    return value === "-" ? "no label reading. Thank you, someone else will be asked" : `the label reads ${value}. Thank you`;
  }
  return outcomeWord(x.outcome);
}

function modelName(model: string | undefined, fallback: string): string {
  return (model ?? fallback).replace(/^prisma-/i, "Prisma ").replace(/^timbre-/i, "Timbre ");
}

export default function JoinPage() {
  return (
    <Suspense>
      <JoinInner />
    </Suspense>
  );
}

function JoinInner() {
  const { token } = useParams<{ token: string }>();
  const search = useSearchParams();
  const isPreview = PREVIEW_ENABLED && token === "preview";
  const payload: JoinPayload | null = isPreview ? { i: "preview-0001", p: search.get("p") ?? "p_mahesh", s: "preview", t: "preview" } : decodeJoin(token);

  return (
    <div className="app-root min-h-dvh bg-ink text-cream">
      <div className="mx-auto flex min-h-dvh w-full max-w-[520px] flex-col px-5 pb-8 pt-5">
        <header className="flex items-center justify-between">
          <Wordmark />
          {isPreview ? (
            <span className="rounded-full border border-dashed border-warn/60 px-2.5 py-1 text-[11px] font-medium text-warn">Preview data</span>
          ) : (
            <span className="rounded-full bg-white/[.06] px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.1em] text-fg-2">Simulation</span>
          )}
        </header>
        {payload ? <Participant payload={payload} preview={isPreview} /> : <Invalid />}
      </div>
    </div>
  );
}

function Invalid() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center text-center">
      <h1 className="display-slab text-[44px]">This link does not work</h1>
      <p className="mt-3 max-w-[32ch] text-[15px] text-cream/70">It may be incomplete. Ask the person who sent it for a new one.</p>
    </div>
  );
}

/** "checking": re-reading the question after a drop. "unverified": that check failed, so whether
 * the last answer arrived is unknown; answering stays blocked until a retry succeeds. */
type Phase = "idle" | "recording" | "sending" | "checking" | "unverified";
/** The call over one socket (services/core/.../voice/call.py): ring, consent, then questions. */
type CallPhase = "none" | "connecting" | "consent" | "active" | "ended";

function Participant({ payload, preview }: { payload: JoinPayload; preview: boolean }) {
  const [state, setState] = useState<InvestigationState | null>(null);
  const [view, setView] = useState<ParticipantView | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [understood, setUnderstood] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [text, setText] = useState("");
  const [moved, setMoved] = useState<string | null>(null);
  const recRef = useRef<Recording | null>(null);
  const liveRef = useRef<QuestionMediaSession | null>(null);
  const callRef = useRef<QuestionMediaSession | null>(null);
  const [callPhase, setCallPhase] = useState<CallPhase>("none");
  const [voiceInfo, setVoiceInfo] = useState<MediaReady | null>(null);
  const [detectedLanguage, setDetectedLanguage] = useState<string | null>(null);
  const [consentText, setConsentText] = useState<string | null>(null);
  const levelRef = useRef(0);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const listenRef = useRef<WavStreamPlayback | null>(null);

  const load = useCallback(async () => {
    try {
      if (preview) {
        const f = await import("@/lib/preview/fixtures");
        setState(f.previewInvestigation);
        setView({ location_label: "the guard desk", items: [{ label: "Hostel Wi-Fi on your phone", value: "connected" }, { label: "Lights", value: "on" }], reachable_locations: [] });
        return;
      }
      const s = await participantApi(payload).getInvestigation();
      setState(s);
      setError(null);
      sim.view(payload.s, payload.t).then(setView).catch(() => setView(null));
    } catch (e) {
      setError(e);
    }
    // payload is decoded from the URL on every render; these fields are its whole identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload.i, payload.s, payload.t, payload.o, payload.p, preview]);

  useEffect(() => {
    // load() only sets state after awaiting the network or a dynamic import.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    if (preview) return;
    const id = setInterval(load, 2500);
    return () => clearInterval(id);
  }, [load, preview]);

  useEffect(
    () => () => {
      recRef.current?.cancel();
      liveRef.current?.close();
      callRef.current?.close();
      listenRef.current?.stop();
      void audioCtxRef.current?.close();
    },
    [],
  );

  if (error && !state)
    return (
      <div className="flex flex-1 flex-col items-center justify-center text-center" role="alert">
        <h1 className="display-slab text-[40px]">{error instanceof ApiError && error.status === 404 ? "This investigation has ended" : "Cannot connect"}</h1>
        <p className="mt-3 max-w-[34ch] text-[15px] text-cream/70">{describeError(error)}</p>
        <button type="button" onClick={load} className="btn-line mt-6">
          Try again
        </button>
      </div>
    );
  if (!state)
    return (
      <div className="flex flex-1 items-center justify-center text-[14px] text-cream/60" aria-busy="true">
        Connecting...
      </div>
    );

  const me = state.participants.find((p) => p.id === payload.p);
  const q =
    state.pending_questions?.find((w) => w.action.participant_id === payload.p) ??
    (state.pending_question && state.pending_question.action.participant_id === payload.p ? state.pending_question : null);
  const needsMove = q?.action.requires_move && moved !== q.id;
  const place = q ? (state.participants.length ? q.action.location_id : "") : "";
  const grant = state.approvals?.find((a) => a.participant_id === payload.p && a.status === "approved");

  const sendAnswer = async (body: { outcome?: string; text?: string }) => {
    if (!q || phase !== "idle") return;
    setMsg(null);
    setUnderstood(null);
    if (preview) {
      setUnderstood(`I understood: ${outcomeWord(body.outcome ?? "your answer")}. (Preview: nothing was sent.)`);
      return;
    }
    setPhase("sending");
    try {
      const r = await participantApi(payload).answer({
        question_id: q.id,
        participant_id: payload.p,
        ...(body.outcome ? { outcome: body.outcome, modality: "tap" as const } : { text: body.text, modality: "text" as const }),
      });
      setUnderstood(`I understood: ${heardAs(r.extraction)}`);
      setText("");
      setState(r.state);
    } catch (e) {
      setMsg(describeError(e));
    } finally {
      setPhase("idle");
    }
  };

  const recoverConnection = async () => {
    setPhase("checking");
    setMsg("The voice connection closed. Checking the current question before you try again.");
    try {
      const current = await participantApi(payload).getInvestigation();
      setState(current);
      setMsg("The voice connection closed. If a question is still open, you can answer by voice, tapping, or typing.");
      setPhase("idle");
    } catch {
      setPhase("unverified");
      setMsg("We could not check whether your answer was received. Check the connection, then try again.");
    }
  };

  /** Accept the incoming call: open the call socket, answer the ring, wait for the consent line. */
  const acceptCall = async () => {
    if (preview) return;
    setMsg(null);
    setCallPhase("connecting");
    let heard = "";
    let callEnded = false;
    let callConnected = false;
    const session: QuestionMediaSession = new QuestionMediaSession(
      payload.i,
      "",
      payload.t,
      {
        onConsentRequest: (text) => {
          setConsentText(text);
          setCallPhase("consent");
        },
        onReady: (info) => setVoiceInfo(info),
        onLevel: (rms) => {
          levelRef.current = rms;
        },
        onTranscript: (t) => {
          heard = t.text;
          setDetectedLanguage(t.detected_language);
        },
        onAnswer: (result) => {
          const r = result as AnswerResult;
          setUnderstood(`I heard "${heard}" and understood: ${heardAs(r.extraction)}`);
          setState(r.state);
          session.endTurn();
          setPhase("idle");
        },
        onEmptyTranscript: () => {
          setMsg("Nothing was heard. Please try again a little closer to the microphone.");
          session.endTurn();
          setPhase("idle");
        },
        onQuestionWithdrawn: () => {
          setPhase("idle");
          load();
        },
        onReprompt: (text) => setHint(text || "Are you still there? Please answer when you are ready."),
        onError: (e) => {
          if (e.fatal) setMsg(describeError(new ApiError(e.status, e.code, e.message, null)));
        },
        onCallEnd: (reason) => {
          callEnded = true;
          setCallPhase("ended");
          setPhase("idle");
          setHint(null);
          if (reason === "silent") setMsg("We could not hear you, so the call ended. Others will be asked instead.");
          load();
        },
        onClose: () => {
          if (callRef.current === session) callRef.current = null;
          if (!callConnected) return;
          setCallPhase((c) => (c === "none" ? c : "ended"));
          if (callEnded) setPhase("idle");
          else void recoverConnection();
        },
      },
      { callParticipantId: payload.p, playQuestion: false, organization: payload.o },
    );
    try {
      const ready = await Promise.race([
        session.connect(),
        new Promise((_, reject) => setTimeout(() => reject(new Error("call socket timeout")), 5000)),
      ]);
      setVoiceInfo(ready as MediaReady);
    } catch {
      session.close();
      setCallPhase("none");
      setMsg("The call could not connect. You can still answer below.");
      return;
    }
    callConnected = true;
    callRef.current = session;
    session.accept();
  };

  // "Not now" only dismisses the call: the question below can still be answered by tapping or
  // typing. Saying No or Later at the consent step is what takes the person out.
  const declineCall = () => setCallPhase("ended");

  const giveConsent = (answer: "yes" | "no" | "later") => {
    callRef.current?.consent(answer);
    setConsentText(null);
    setCallPhase(answer === "yes" ? "active" : "ended");
  };

  /**
   * Live voice over the media socket: the microphone streams to the core while the person
   * speaks, and the answer is recorded as soon as they stop. Returns false if the socket
   * cannot be used, so the caller falls back to recording a clip and uploading it.
   */
  const startLive = async (question: NonNullable<typeof q>): Promise<boolean> => {
    let heard = "";
    let finished = false;
    let connected = false;
    let socketLost = false;
    setHint(null);
    const done = (session: QuestionMediaSession) => {
      finished = true;
      setHint(null);
      session.close();
      if (liveRef.current === session) liveRef.current = null;
      levelRef.current = 0;
      setPhase("idle");
    };
    const session: QuestionMediaSession = new QuestionMediaSession(
      payload.i,
      question.id,
      payload.t,
      {
        onLevel: (rms) => {
          levelRef.current = rms;
        },
        onTranscript: (t) => {
          heard = t.text;
          setDetectedLanguage(t.detected_language);
        },
        onReady: (info) => {
          setVoiceInfo(info);
          setDetectedLanguage(null);
        },
        onAnswer: (result) => {
          const r = result as AnswerResult;
          setUnderstood(`I heard "${heard}" and understood: ${heardAs(r.extraction)}`);
          setState(r.state);
          done(session);
        },
        onEmptyTranscript: () => {
          setMsg("Nothing was heard. Please try again a little closer to the microphone.");
          done(session);
        },
        onError: (e) => {
          if (!e.fatal) return;
          done(session);
          if (e.status >= 500 || ["VOICE_STREAM_CLOSED", "VOICE_UNREACHABLE", "VOICE_TIMEOUT"].includes(e.code)) {
            void recoverConnection();
          } else {
            setMsg(describeError(new ApiError(e.status, e.code, e.message, null)));
          }
        },
        // The call runtime asks again after a silence; show what it said.
        onReprompt: (text) => setHint(text || "Are you still there? Please answer when you are ready."),
        onClose: (code) => {
          if (finished) return;
          if (!connected) return;
          socketLost = true;
          // 4408: twenty seconds of silence. The question stays open, so they can simply retry.
          done(session);
          if (code === 4408) setMsg("We could not hear you. Checking the question before you try again.");
          void recoverConnection();
        },
      },
      { playQuestion: false, organization: payload.o },
    );
    try {
      const ready = await Promise.race([
        session.connect(),
        new Promise((_, reject) => setTimeout(() => reject(new Error("media socket timeout")), 4000)),
      ]);
      setVoiceInfo(ready as MediaReady);
      setDetectedLanguage(null);
      connected = true;
      await session.startMic();
    } catch {
      session.close();
      return socketLost;
    }
    if (socketLost) return true;
    liveRef.current = session;
    setPhase("recording");
    return true;
  };

  const toggleVoice = async () => {
    if (!q) return;
    setMsg(null);
    setUnderstood(null);
    const call = callPhase === "active" ? callRef.current : null;
    if (call) {
      if (phase === "recording") {
        setPhase("sending");
        call.commit();
        return;
      }
      try {
        await call.startMic();
        setPhase("recording");
      } catch {
        setMsg("The microphone is not available. Allow microphone access, or answer by tapping or typing.");
      }
      return;
    }
    if (phase === "recording" && liveRef.current) {
      setPhase("sending");
      liveRef.current.commit();
      return;
    }
    if (phase === "recording") {
      const rec = recRef.current;
      recRef.current = null;
      if (!rec) return;
      setPhase("sending");
      try {
        const wav = await rec.stop();
        if (preview) {
          setUnderstood("Recorded. (Preview: nothing was sent.)");
        } else {
          const r = await participantApi(payload).answerByVoice(q.id, wav);
          setUnderstood(`I heard "${r.stt.transcript}" and understood: ${heardAs(r.result.extraction)}`);
          setState(r.result.state);
        }
      } catch (e) {
        setMsg(describeError(e));
      } finally {
        setPhase("idle");
        levelRef.current = 0;
      }
      return;
    }
    if (!preview && (await startLive(q))) return;
    try {
      const rec = await startRecording();
      recRef.current = rec;
      setPhase("recording");
    } catch {
      setMsg("The microphone is not available. Allow microphone access, or answer by tapping or typing.");
    }
  };

  const playQuestion = async () => {
    if (!q || preview) {
      setMsg(preview ? "Audio playback needs the core. (Preview)" : null);
      return;
    }
    try {
      // Played while it downloads: an uncached question starts before synthesis finishes.
      const ctx = (audioCtxRef.current ??= new AudioContext());
      // Never wait on resume(): it stays pending until the browser sees a user gesture.
      if (ctx.state === "suspended") void ctx.resume();
      listenRef.current?.stop();
      const res = await participantApi(payload).questionAudioStream(q.id);
      const playback = playWavStream(res, ctx);
      listenRef.current = playback;
      await playback.done;
    } catch (e) {
      setMsg(describeError(e));
    }
  };

  return (
    <main className="flex flex-1 flex-col">
      <p className="mt-8 text-[15px] text-cream/70">
        {me ? <>Hello {me.display_name}.</> : <>Hello.</>} {view ? <>You are at {view.location_label}.</> : null}
      </p>

      {q && callPhase !== "consent" && callPhase !== "connecting" ? (
        <div data-testid="participant-current-step" aria-live="polite" className="mt-4 rounded-[16px] border border-info/40 bg-info/[.06] p-4">
          {q.kind === "confirm" ? <span className="mb-2 inline-flex rounded-full bg-warn/15 px-2.5 py-1 text-[12px] text-warn">Just checking</span> : null}
          {q.kind === "challenge" ? <span className="mb-2 inline-flex rounded-full bg-cream/15 px-2.5 py-1 text-[12px] text-cream">Quick location check</span> : null}
          <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-info">Question for {me?.display_name ?? "you"}</p>
          <h1 lang={q.language === "hi-en" ? "hi-Latn" : q.language} className="mt-1 text-[23px] font-medium leading-snug">{q.text}</h1>
          <p className="mt-2 text-[13px] leading-relaxed text-fg-2">
            <span className="font-medium text-fg">Why this check: </span>
            Your answer adds an observation that helps narrow the reported problem.
          </p>
        </div>
      ) : null}

      <div className="relative mt-4 h-[150px] overflow-hidden">
        <VoiceField
          modes={["lens"]}
          className="absolute inset-0 h-full w-full"
          level={phase === "recording" ? () => recRef.current?.level() ?? levelRef.current : undefined}
          ariaLabel={phase === "recording" ? "Microphone level" : "Decorative waveform"}
        />
      </div>

      {q && !preview && callPhase === "none" ? (
        <section aria-live="polite" className="mt-2 rounded-[18px] border-[0.8px] border-cream/20 p-5 text-center">
          <p className="text-[13px] uppercase tracking-[0.12em] text-cream/60">Incoming call</p>
          <h2 className="display-slab mt-2 text-[34px]">Pramana is calling</h2>
          <p className="mx-auto mt-2 max-w-[32ch] text-[15px] text-cream/70">It needs a minute of your help with a problem in the building.</p>
          <div className="mt-5 grid grid-cols-2 gap-3">
            <button type="button" onClick={declineCall} className="btn-line lg w-full">
              Not now
            </button>
            <button type="button" onClick={acceptCall} className="btn-line lg w-full !bg-cream !text-ink">
              Accept
            </button>
          </div>
        </section>
      ) : null}
      {callPhase === "connecting" ? (
        <p aria-live="polite" className="mt-4 text-center text-[14px] text-cream/60">
          Connecting the call...
        </p>
      ) : null}
      {callPhase === "consent" && consentText ? (
        <section aria-live="polite" className="mt-2 rounded-[18px] border-[0.8px] border-cream/20 p-5">
          <h2 lang={me?.languages.template_language === "hi-en" ? "hi-Latn" : me?.languages.template_language} className="text-[20px] leading-snug">
            {consentText}
          </h2>
          <div className="mt-5 grid grid-cols-3 gap-2" role="group" aria-label="Consent">
            <button type="button" onClick={() => giveConsent("no")} className="btn-line w-full">
              No
            </button>
            <button type="button" onClick={() => giveConsent("later")} className="btn-line w-full">
              Later
            </button>
            <button type="button" onClick={() => giveConsent("yes")} className="btn-line w-full !bg-cream !text-ink">
              Yes
            </button>
          </div>
        </section>
      ) : null}

      {q && callPhase !== "consent" && callPhase !== "connecting" ? (
        <section aria-live="polite" className="mt-2 flex flex-col">
          {voiceInfo ? (
            <div className="mt-2 flex flex-wrap gap-2 text-[12px]" aria-live="polite">
              {voiceInfo.protocol_emulator ? (
                <span className="rounded-full border border-warn/50 bg-warn/10 px-2.5 py-1 text-warn">Gnani protocol emulator - synthetic audio</span>
              ) : voiceInfo.provider !== "gnani" ? (
                <span className="rounded-full border border-line px-2.5 py-1 text-[12px] text-muted">Voice provider: {voiceInfo.provider ?? "unknown"}</span>
              ) : (
                <span className="rounded-full border border-line px-2.5 py-1 text-muted">{modelName(voiceInfo.stt_model, "Prisma")} / {modelName(voiceInfo.tts_model, "Timbre")} · {voiceInfo.language}</span>
              )}
              {detectedLanguage ? <span className="rounded-full border border-line px-2.5 py-1 text-muted">Detected: {detectedLanguage}</span> : null}
            </div>
          ) : null}
          <button type="button" onClick={playQuestion} className="mt-3 flex w-fit items-center gap-2 text-[14px] text-cream/70 hover:text-cream">
            <IconPlay className="h-4 w-4" /> Listen to the question
          </button>

          {needsMove ? (
            <div className="mt-6 rounded-[16px] border-[0.8px] border-cream/20 p-4">
              <p className="text-[15px]">First, please go to the place in the question.</p>
              <button
                type="button"
                className="btn-line lg mt-4 w-full !bg-cream !text-ink"
                onClick={async () => {
                  setMsg(null);
                  try {
                    if (!preview) await sim.move(payload.s, payload.t, place);
                    setMoved(q.id);
                  } catch (e) {
                    setMsg(describeError(e));
                  }
                }}
              >
                I am there now
              </button>
            </div>
          ) : (
            <>
              <div className="mt-6 grid grid-cols-2 gap-3" role="group" aria-label="Answers">
                {q.outcomes.map((o) => (
                  <button
                    key={o}
                    type="button"
                    disabled={phase !== "idle"}
                    onClick={() => sendAnswer({ outcome: o })}
                    className="btn-line lg min-h-[60px] w-full text-[15px] disabled:opacity-40"
                  >
                    {outcomeWord(o)}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={toggleVoice}
                disabled={phase === "sending" || phase === "checking" || phase === "unverified"}
                aria-pressed={phase === "recording"}
                className={clsx(
                  "mt-4 flex h-[64px] w-full items-center justify-center gap-3 rounded-full text-[16px] font-semibold transition-colors duration-300 disabled:opacity-50",
                  phase === "recording" ? "bg-bad text-white" : "bg-cream text-ink",
                )}
              >
                <IconMic />
                {phase === "recording" ? "Stop and send" : phase === "sending" ? "Sending..." : phase === "checking" ? "Checking..." : "Answer by voice"}
              </button>
              <form
                className="mt-4 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (text.trim()) sendAnswer({ text: text.trim() });
                }}
              >
                <label htmlFor="ans" className="sr-only">
                  Type your answer
                </label>
                <input
                  id="ans"
                  value={text}
                  disabled={phase === "checking" || phase === "unverified"}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={q.kind === "challenge" ? "Type what the label says" : "Or type your answer"}
                  className="h-[52px] min-w-0 flex-1 border-[0.8px] border-cream/40 bg-transparent px-4 text-[16px] outline-none transition-[border-radius] duration-500 placeholder:text-cream/40 focus:rounded-[26px] focus:border-cream"
                />
                <button type="submit" className="btn-line" disabled={!text.trim() || phase !== "idle"}>
                  Send
                </button>
              </form>
            </>
          )}
        </section>
      ) : grant ? (
        <Repair state={state} approval={grant} payload={payload} preview={preview} onState={setState} />
      ) : (
        <section className="mt-6 text-center" aria-live="polite">
          <h1 className="display-slab text-[38px]">Nothing to answer right now</h1>
          <p className="mx-auto mt-3 max-w-[32ch] text-[15px] text-cream/70">Keep this page open. A question will appear here if Pramana needs your help.</p>
          <DeviceCheck audioCtxRef={audioCtxRef} />
        </section>
      )}

      {hint ? (
        <p aria-live="polite" className="mt-5 rounded-[14px] bg-cream/10 px-4 py-3 text-[15px] text-cream">
          {hint}
        </p>
      ) : null}
      {understood ? (
        <p role="status" className="mt-5 rounded-[14px] bg-ok/10 px-4 py-3 text-[15px] text-ok">
          {understood}
        </p>
      ) : null}
      {msg ? (
        <p role="alert" className="mt-5 rounded-[14px] bg-bad/10 px-4 py-3 text-[14px] text-[#ff8a7f]">
          {msg}
        </p>
      ) : null}
      {phase === "unverified" ? (
        <button type="button" onClick={recoverConnection} className="btn-line mt-3">
          Check connection
        </button>
      ) : null}

      {view && (view.items.length || view.labels?.length) ? (
        <details className="mt-auto pt-8 text-[14px]">
          <summary className="cursor-pointer text-cream/60">What you can see here (simulation)</summary>
          <dl className="mt-3 divide-y divide-cream/10">
            {view.items.map((it) => (
              <div key={it.label} className="flex justify-between gap-4 py-2">
                <dt className="text-cream/60">{it.label}</dt>
                <dd>{it.value}</dd>
              </div>
            ))}
            {(view.labels ?? []).map((l) => (
              <div key={l.token_id} className="flex justify-between gap-4 py-2">
                <dt className="text-cream/60">{l.label}</dt>
                <dd className="font-mono tracking-[0.2em]">{l.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
      <p className="mt-6 text-center text-[12px] text-cream/70">
        Answers go to the people running this investigation. <Link href="/" className="underline">About Pramana</Link>
      </p>
    </main>
  );
}

function Repair({
  approval,
  payload,
  preview,
  onState,
}: {
  state: InvestigationState;
  approval: Approval;
  payload: JoinPayload;
  preview: boolean;
  onState: (s: InvestigationState) => void;
}) {
  const [cap, setCap] = useState<{ capability: string; instructions: string; expires_at: string; location_id?: string | null } | null>(null);
  const [there, setThere] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <section className="mt-4" aria-live="polite">
      <h1 className="display-slab text-[36px]">You are cleared to act</h1>
      <p className="mt-2 text-[15px] text-cream/75">
        {approval.action_label} on <span className="font-mono">{approval.target}</span>.{" "}
        {approval.requested_by && approval.approver_id
          ? "It was requested by one staff account and approved by another. The requester cannot approve their own request."
          : "Pramana did not record both accounts, so it cannot confirm that the approval came from someone other than the requester."}
      </p>
      <p className="mt-2 text-[13px] text-cream/75">This simulated repair uses a permission once. It expires five minutes after you collect it.</p>
      {!cap ? (
        <button
          type="button"
          className="btn-line lg mt-6 w-full !bg-cream !text-ink"
          disabled={busy || preview}
          onClick={async () => {
            setBusy(true);
            setErr(null);
            try {
              setCap(await participantApi(payload).collectCapability(approval.id));
            } catch (e) {
              setErr(describeError(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Collect permission
        </button>
      ) : (
        <div className="mt-6 rounded-[16px] border-[0.8px] border-cream/20 p-4">
          <p className="text-[16px]">{cap.instructions}</p>
          <p className="mt-2 text-[13px] text-cream/60">Valid until {new Date(cap.expires_at).toLocaleTimeString()}.</p>
          {cap.location_id && !there ? (
            <button
              type="button"
              className="btn-line lg mt-4 w-full !bg-cream !text-ink"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setErr(null);
                try {
                  await sim.move(payload.s, payload.t, cap.location_id as string);
                  setThere(true);
                } catch (e) {
                  setErr(describeError(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              I am at the panel
            </button>
          ) : (
          <button
            type="button"
            className="btn-line lg mt-4 w-full"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                try {
                  await sim.act(payload.s, payload.t, { action: approval.action, target: approval.target, capability: cap.capability });
                } catch (e) {
                  // This very permission was already used (the report was lost, or the page
                  // reloaded after the reset): the action happened, so report it.
                  if (!(e instanceof ApiError && e.code === "CAPABILITY_USED")) throw e;
                }
                onState(await participantApi(payload).reportIntervention(approval.id));
              } catch (e) {
                if (e instanceof ApiError && e.status === 403 && /expired/i.test(e.message)) {
                  setCap(null);
                  setThere(false);
                  setErr("Your permission expired before it was used. Collect it again.");
                } else {
                  setErr(describeError(e));
                }
              } finally {
                setBusy(false);
              }
            }}
          >
            I have done it
          </button>
          )}
        </div>
      )}
      {err ? <p role="alert" className="mt-4 text-[14px] text-[#ff8a7f]">{err}</p> : null}
    </section>
  );
}
