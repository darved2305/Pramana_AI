"use client";

import { useEffect, useRef } from "react";
import { usePrefersReducedMotion } from "@/lib/hooks/useReducedMotion";

/**
 * Decorative voice visual drawn on a single canvas.
 *
 * Every shape is a function of continuous time (sums of sines with incommensurate
 * frequencies), so there is no loop to restart and therefore no visible seam.
 *
 * `level` is reserved for a future voice-reactive variant: pass a function returning
 * the current amplitude in [0, 1]. Without it the motion is synthetic idle motion and
 * must not be presented as reacting to live audio.
 */
export type VoiceMode = "lens" | "pixels" | "ribbons" | "lines";

export interface VoiceFieldProps {
  /** One mode, or several to cycle through with a crossfade. */
  modes?: VoiceMode[];
  /** Seconds each mode stays on screen when cycling. */
  hold?: number;
  className?: string;
  /** Returns the live audio level in [0, 1]. Only pass this when it is real audio. */
  level?: () => number;
  ariaLabel?: string;
}

const C = {
  lime: "#d6f535",
  blue: "#33a8f5",
  violet: "#a62be6",
  white: "#f5f5f5",
  red: "#c80014",
  magenta: "#e535a8",
};

const FADE = 0.8; // seconds of crossfade between modes (estimated from the reference)

export function VoiceField({
  modes = ["lens"],
  hold = 4.6,
  className,
  level,
  ariaLabel = "Animated voice visual",
}: VoiceFieldProps) {
  const ref = useRef<HTMLCanvasElement>(null);
  const reduced = usePrefersReducedMotion();
  const levelRef = useRef(level);
  useEffect(() => {
    levelRef.current = level;
  }, [level]);
  const modesKey = modes.join(",");

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const list = modesKey.split(",") as VoiceMode[];

    let w = 0;
    let h = 0;
    let dpr = 1;
    let raf = 0;
    let visible = true;
    let start = performance.now();
    let pausedAt = 0;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = Math.max(1, rect.width);
      h = Math.max(1, rect.height);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      const live = levelRef.current ? clamp01(levelRef.current()) : null;
      if (list.length === 1) {
        drawMode(ctx, list[0], t, w, h, 1, live);
        return;
      }
      const cycle = hold * list.length;
      const p = t % cycle;
      const idx = Math.floor(p / hold);
      const within = p - idx * hold;
      const cur = list[idx];
      if (within > hold - FADE) {
        const k = easeInOut((within - (hold - FADE)) / FADE);
        drawMode(ctx, cur, t, w, h, 1 - k, live);
        drawMode(ctx, list[(idx + 1) % list.length], t, w, h, k, live);
      } else {
        drawMode(ctx, cur, t, w, h, 1, live);
      }
    };

    const frame = (now: number) => {
      draw((now - start) / 1000);
      raf = requestAnimationFrame(frame);
    };

    const play = () => {
      if (raf || reduced) return;
      if (pausedAt) start += performance.now() - pausedAt;
      pausedAt = 0;
      raf = requestAnimationFrame(frame);
    };
    const pause = () => {
      if (!raf) return;
      cancelAnimationFrame(raf);
      raf = 0;
      pausedAt = performance.now();
    };

    resize();
    if (reduced) {
      draw(1.7); // a single, settled frame
    } else {
      play();
    }

    const ro = new ResizeObserver(() => {
      resize();
      if (reduced) draw(1.7);
    });
    ro.observe(canvas);

    const io = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        if (visible && !document.hidden) play();
        else pause();
      },
      { rootMargin: "100px" },
    );
    io.observe(canvas);

    const onVis = () => (document.hidden || !visible ? pause() : play());
    document.addEventListener("visibilitychange", onVis);

    return () => {
      cancelAnimationFrame(raf);
      raf = 0;
      ro.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [modesKey, hold, reduced]);

  return <canvas ref={ref} className={className} role="img" aria-label={ariaLabel} />;
}

/* ------------------------------------------------------------------ */

function drawMode(
  ctx: CanvasRenderingContext2D,
  mode: VoiceMode,
  t: number,
  w: number,
  h: number,
  alpha: number,
  live: number | null,
) {
  if (alpha <= 0.001) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  switch (mode) {
    case "lens":
      drawLens(ctx, t, w, h, live);
      break;
    case "pixels":
      drawPixels(ctx, t, w, h, live);
      break;
    case "ribbons":
      drawRibbons(ctx, t, w, h, live);
      break;
    case "lines":
      drawLines(ctx, t, w, h, live);
      break;
  }
  ctx.restore();
}

/** Smooth pseudo-noise from incommensurate sines; continuous in x and t. */
function wave(x: number, t: number, seed: number) {
  return (
    Math.sin(x * 6.1 + t * 1.7 + seed) * 0.42 +
    Math.sin(x * 11.3 - t * 2.3 + seed * 1.9) * 0.3 +
    Math.sin(x * 2.7 + t * 0.9 + seed * 3.1) * 0.28 +
    Math.sin(x * 17.9 + t * 3.1 + seed * 0.7) * 0.12
  );
}

/* ---------- Lens: the lime crescent with flowing lines inside ---------- */

function lensGeometry(t: number, w: number, h: number) {
  // Proportions measured on the reference at 1536 x 730: the lens spans ~60% of the
  // viewport width and its top arc rises ~230px above its end points.
  const size = Math.min(w * 0.6, h * 2.5);
  const cx = w / 2;
  const cy = h * 0.76;
  const rx = size / 2;
  const ryOuter = size * 0.265;
  const ryInner = size * 0.085;
  const tilt = Math.sin(t * 0.45) * 0.035 + Math.sin(t * 0.21 + 1) * 0.015;
  const breathe = 1 + Math.sin(t * 0.8) * 0.012;
  return { cx, cy, rx: rx * breathe, ryOuter: ryOuter * breathe, ryInner, tilt, size };
}

function lensPath(ctx: CanvasRenderingContext2D, g: ReturnType<typeof lensGeometry>) {
  const { rx, ryOuter, ryInner } = g;
  const dip = 0.16; // how far (radians) the outer arc continues below the end points
  ctx.beginPath();
  ctx.ellipse(0, 0, rx, ryOuter, 0, Math.PI - dip, Math.PI * 2 + dip, false);
  ctx.ellipse(0, ryOuter * 0.12, rx * 0.93, ryInner, 0, Math.PI * 2 + 0.05, Math.PI - 0.05, true);
  ctx.closePath();
}

function drawLens(ctx: CanvasRenderingContext2D, t: number, w: number, h: number, live: number | null) {
  const g = lensGeometry(t, w, h);
  const amp = live ?? 0.72 + 0.28 * (0.5 + 0.5 * Math.sin(t * 0.9));
  const stroke = Math.max(1.4, g.size / 520);
  ctx.save();
  ctx.translate(g.cx, g.cy);
  ctx.rotate(g.tilt);

  // Lines clipped inside the crescent.
  ctx.save();
  lensPath(ctx, g);
  ctx.clip();
  const lineW = Math.max(2.4, g.size / 230);
  ctx.lineWidth = lineW;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const span = g.rx * 2.1;
  const steps = 160;
  const traces: { seed: number; base: number; amp: number; color: string; hl: boolean }[] = [
    { seed: 0.3, base: -0.62, amp: 0.36, color: C.blue, hl: true },
    { seed: 2.1, base: -0.05, amp: 0.3, color: C.violet, hl: true },
  ];
  for (const tr of traces) {
    const grad = ctx.createLinearGradient(-span / 2, 0, span / 2, 0);
    if (tr.hl) {
      // A white highlight travels along the line, as on the reference.
      const hp = (t * 0.11 + tr.seed) % 1;
      const stops = [0, Math.max(0, hp - 0.08), hp, Math.min(1, hp + 0.08), 1];
      grad.addColorStop(stops[0], tr.color);
      grad.addColorStop(stops[1], tr.color);
      grad.addColorStop(stops[2], C.white);
      grad.addColorStop(stops[3], tr.color);
      grad.addColorStop(stops[4], tr.color);
    } else {
      grad.addColorStop(0, tr.color);
      grad.addColorStop(1, tr.color);
    }
    ctx.strokeStyle = grad;
    ctx.beginPath();
    for (let i = 0; i <= steps; i++) {
      const u = i / steps;
      const x = -span / 2 + u * span;
      const y = (tr.base + wave(u * 3.1, t, tr.seed) * tr.amp * amp) * g.ryOuter;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
  ctx.restore();

  // Crescent outline.
  ctx.strokeStyle = C.lime;
  ctx.lineWidth = stroke;
  lensPath(ctx, g);
  ctx.stroke();

  // Orbiting arc fragments and a floating dot, outside the lens.
  ctx.lineCap = "round";
  const orbit = (a0: number, len: number, scale: number) => {
    ctx.beginPath();
    ctx.ellipse(0, g.ryOuter * 0.1, g.rx * scale, g.ryOuter * scale * 0.95, 0, a0, a0 + len);
    ctx.stroke();
  };
  const drift = Math.sin(t * 0.6) * 0.06;
  orbit(Math.PI * 1.04 + drift, 0.11, 1.09);
  orbit(Math.PI * 0.08 - drift, 0.12, 1.1);
  const dotA = Math.PI * 1.55 + Math.sin(t * 0.5) * 0.25;
  const dx = Math.cos(dotA) * g.rx * 0.08;
  const dy = g.ryOuter * (-0.22 + Math.sin(t * 0.7) * 0.06);
  ctx.beginPath();
  ctx.moveTo(dx, dy);
  ctx.lineTo(dx + stroke * 2.2, dy + stroke * 6);
  ctx.stroke();
  ctx.fillStyle = C.lime;
  ctx.beginPath();
  ctx.arc(g.rx * 0.52 + Math.sin(t * 0.4) * 6, -g.ryOuter * 0.86 + Math.cos(t * 0.55) * 4, stroke * 1.6, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

/* ---------- Pixels: a grid of squares forming a speaking mouth ---------- */

function drawPixels(ctx: CanvasRenderingContext2D, t: number, w: number, h: number, live: number | null) {
  // Reference cells are ~22px with ~6px gaps at 1536px wide.
  const cell = Math.max(8, Math.round(w / 70));
  const gap = Math.max(2, Math.round(cell * 0.27));
  const pitch = cell + gap;
  const cols = Math.floor(w / pitch);
  const rows = Math.min(14, Math.floor((h * 0.9) / pitch));
  const ox = (w - cols * pitch + gap) / 2;
  const oy = h - rows * pitch - h * 0.02;
  const open = live ?? 0.55 + 0.45 * Math.abs(Math.sin(t * 1.3) * Math.sin(t * 0.47 + 0.6));
  const mid = rows * 0.55;

  for (let c = 0; c < cols; c++) {
    const u = c / (cols - 1);
    const edge = Math.min(1, 1.6 * Math.pow(Math.sin(Math.PI * u), 0.9)); // fade toward the sides
    const centre = 1 - Math.abs(u - 0.5) * 2;
    // Mouth: an upper and a lower lip curve; open more in the middle.
    const lipTop = mid - (1.2 + 3.4 * open * Math.pow(centre, 0.8)) + wave(u, t, 1) * 0.4;
    const lipBot = mid + (0.6 + 2.6 * open * Math.pow(centre, 1.1)) + wave(u, t, 4) * 0.4;
    const spike = Math.max(0, Math.sin(u * 23 + t * 2.1) * Math.sin(u * 7 - t * 1.3)) > 0.82;
    for (let r = 0; r < rows; r++) {
      const inMouth = r > lipTop && r < lipBot;
      const nearLip = Math.min(Math.abs(r - lipTop), Math.abs(r - lipBot)) < 0.8;
      let b: number;
      if (inMouth && !nearLip) b = 0.06;
      else if (nearLip) b = 1;
      else b = 0.62 + 0.38 * (0.5 + 0.5 * Math.sin(c * 0.9 + r * 1.3 + t * 2));
      if (spike) b = Math.max(b, 0.9);
      const vfade = 0.55 + 0.45 * Math.sin((Math.PI * (r + 0.5)) / rows);
      const a = b * edge * vfade;
      if (a < 0.04) continue;
      ctx.fillStyle = `rgba(51,168,245,${a.toFixed(3)})`;
      ctx.fillRect(ox + c * pitch, oy + r * pitch, cell, cell);
    }
  }
}

/* ---------- Ribbons: layered, additive filled waves ---------- */

function drawRibbons(ctx: CanvasRenderingContext2D, t: number, w: number, h: number, live: number | null) {
  const cy = h * 0.75;
  const amp = (live ?? 0.8) * h * 0.3;
  const layers = [
    { color: "166,43,230", seed: 0.4, k: 1, a: 0.55 },
    { color: "229,53,168", seed: 2.2, k: 0.7, a: 0.6 },
    { color: "255,120,220", seed: 4.1, k: 0.45, a: 0.7 },
  ];
  ctx.globalCompositeOperation = "lighter";
  const steps = 140;
  const x0 = w * 0.06;
  const span = w * 0.88;
  for (const L of layers) {
    ctx.beginPath();
    for (let i = 0; i <= steps; i++) {
      const u = i / steps;
      const env = Math.pow(Math.sin(Math.PI * u), 1.6);
      const y = Math.abs(wave(u * 1.1, t * 0.7, L.seed)) * env * amp * L.k;
      const x = x0 + u * span;
      if (i === 0) ctx.moveTo(x, cy - y);
      else ctx.lineTo(x, cy - y);
    }
    for (let i = steps; i >= 0; i--) {
      const u = i / steps;
      const env = Math.pow(Math.sin(Math.PI * u), 1.6);
      const y = Math.abs(wave(u * 1.1, t * 0.7, L.seed + 1.3)) * env * amp * L.k * 0.8;
      ctx.lineTo(x0 + u * span, cy + y);
    }
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, cy - amp, 0, cy + amp);
    grad.addColorStop(0, `rgba(${L.color},${L.a * 0.6})`);
    grad.addColorStop(0.5, `rgba(${L.color},${L.a})`);
    grad.addColorStop(1, `rgba(${L.color},${L.a * 0.6})`);
    ctx.fillStyle = grad;
    ctx.fill();
  }
  // Bright core line.
  ctx.globalCompositeOperation = "source-over";
  const core = ctx.createLinearGradient(x0, 0, x0 + span, 0);
  core.addColorStop(0, "rgba(255,170,240,0)");
  core.addColorStop(0.5, "rgba(255,190,245,0.9)");
  core.addColorStop(1, "rgba(255,170,240,0)");
  ctx.fillStyle = core;
  ctx.fillRect(x0, cy - 1.5, span, 3);
}

/* ---------- Lines: four free-running strokes ---------- */

function drawLines(ctx: CanvasRenderingContext2D, t: number, w: number, h: number, live: number | null) {
  const cy = h * 0.56;
  const amp = (live ?? 0.85) * h * 0.24;
  const lw = Math.max(2.4, w / 330);
  ctx.lineWidth = lw;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const traces = [
    { c: C.violet, s: 0.2, o: -0.25 },
    { c: C.blue, s: 1.7, o: 0.1 },
    { c: C.lime, s: 3.3, o: 0.2 },
    { c: C.white, s: 5.1, o: -0.05 },
  ];
  const steps = 220;
  for (const tr of traces) {
    ctx.strokeStyle = tr.c;
    ctx.beginPath();
    for (let i = 0; i <= steps; i++) {
      const u = i / steps;
      const y = cy + (tr.o + wave(u * 2.6, t * 0.9, tr.s)) * amp;
      const x = u * w;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
}

function clamp01(v: number) {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}
function easeInOut(x: number) {
  return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
}
