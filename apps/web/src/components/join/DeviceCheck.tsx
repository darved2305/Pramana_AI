"use client";

import { useRef, useState, type MutableRefObject } from "react";

type Result = "idle" | "checking" | "ok" | "silent" | "blocked" | "unsupported";

const LISTEN_MS = 3000;
const HEARD = 0.02; // RMS above room hiss: someone spoke

const TEXT: Record<Exclude<Result, "idle" | "checking">, string> = {
  ok: "Your microphone works and the sound is on. You are ready for the call.",
  silent: "The microphone is on, but nothing was heard. Check that it is not muted, then try again.",
  blocked: "Microphone access is blocked. Allow it for this site in your browser settings, then try again. You can still answer by tapping or typing.",
  unsupported: "This browser cannot use the microphone here (it needs a secure https link). You can still answer by tapping or typing.",
};

/**
 * Before any call: ask for the microphone, show a live level while the person says a word, and
 * play a short tone. The tap is also the user gesture that lets the page play questions later.
 * Nothing is recorded or sent anywhere.
 */
export function DeviceCheck({ audioCtxRef }: { audioCtxRef: MutableRefObject<AudioContext | null> }) {
  const [result, setResult] = useState<Result>("idle");
  const [level, setLevel] = useState(0);
  const running = useRef(false);

  const check = async () => {
    if (running.current) return;
    running.current = true;
    setResult("checking");
    setLevel(0);
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        setResult("unsupported");
        return;
      }
      const ctx = (audioCtxRef.current ??= new AudioContext());
      if (ctx.state === "suspended") void ctx.resume();
      beep(ctx);
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      } catch (e) {
        const name = (e as Error).name;
        setResult(name === "NotAllowedError" || name === "SecurityError" ? "blocked" : "unsupported");
        return;
      }
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      let peak = 0;
      const started = performance.now();
      await new Promise<void>((resolve) => {
        const tick = () => {
          analyser.getFloatTimeDomainData(buf);
          let sum = 0;
          for (const v of buf) sum += v * v;
          const rms = Math.sqrt(sum / buf.length);
          peak = Math.max(peak, rms);
          setLevel(Math.min(1, rms * 8));
          if (performance.now() - started < LISTEN_MS) setTimeout(tick, 50);
          else resolve();
        };
        tick();
      });
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      setResult(peak >= HEARD ? "ok" : "silent");
    } finally {
      running.current = false;
      setLevel(0);
    }
  };

  return (
    <div className="mx-auto mt-6 max-w-[34ch] rounded-[16px] border-[0.8px] border-cream/20 p-4 text-left" aria-label="Device check">
      <button type="button" onClick={check} disabled={result === "checking"} className="btn-line w-full">
        {result === "checking" ? "Listening... say hello" : result === "idle" ? "Check microphone and sound" : "Check again"}
      </button>
      {result === "checking" ? (
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-cream/10" role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={1} aria-valuenow={Number(level.toFixed(2))}>
          <div className="h-full rounded-full bg-cream transition-[width] duration-75" style={{ width: `${Math.round(level * 100)}%` }} />
        </div>
      ) : null}
      {result !== "idle" && result !== "checking" ? (
        <p role="status" className={result === "ok" ? "mt-3 text-[14px] text-ok" : "mt-3 text-[14px] text-[#ffb27f]"}>
          {TEXT[result]}
        </p>
      ) : null}
    </div>
  );
}

/** A short, quiet tone so the person can tell the sound is on. */
function beep(ctx: AudioContext) {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.frequency.value = 660;
  gain.gain.value = 0.08;
  osc.connect(gain).connect(ctx.destination);
  osc.start();
  osc.stop(ctx.currentTime + 0.35);
}
