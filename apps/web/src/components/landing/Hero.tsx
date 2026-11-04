"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { VoiceField } from "@/components/voice/VoiceField";
import { BlurText } from "@/components/motion/BlurText";
import { Arrow } from "./SiteNav";
import { usePrefersReducedMotion } from "@/lib/hooks/useReducedMotion";

/**
 * Hero composition measured at 1536 x 730 on the reference: headline top at 120px (90px
 * slab, light), subline 20/30 at 222px, CTA at 283px, voice canvas from ~380px down to a
 * strip of marks near the bottom edge.
 */
export function Hero() {
  const reduced = usePrefersReducedMotion();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(id);
  }, []);
  const shown = ready || reduced;
  const fade = (d: number) => ({
    opacity: shown ? 1 : 0,
    transform: shown ? "none" : "translateY(10px)",
    transition: reduced ? "none" : `opacity 1s cubic-bezier(.22,1,.36,1) ${d}s, transform 1s cubic-bezier(.22,1,.36,1) ${d}s`,
  });

  return (
    <section
      aria-labelledby="hero-title"
      className="relative isolate flex min-h-[640px] h-[100svh] max-h-[1000px] flex-col overflow-hidden bg-ink text-cream"
    >
      <div className="relative z-10 flex flex-col items-center px-[var(--gutter)] pt-[118px] text-center lg:pt-[120px]">
        <BlurText
          as="h1"
          trigger="load"
          delay={0.15}
          text="An AI that investigates what it cannot see"
          className="display-slab mx-auto max-w-[15ch] text-[clamp(42px,4.8vw,84px)] lg:max-w-none lg:whitespace-nowrap"
        />
        <p
          style={fade(0.55)}
          className="mt-[20px] max-w-[64ch] text-[clamp(16px,1.3vw,20px)] leading-[1.5] text-cream/95"
        >
          When the answer exists only in the physical world, Pramana finds the right people, asks the right
          questions, and turns what they observe into evidence.
        </p>
        <div style={fade(0.75)} className="mt-[30px] flex flex-wrap items-center justify-center gap-[13px]">
          <Link href="/preview/app" className="btn-line lg">
            Open the preview <Arrow />
          </Link>
        </div>
      </div>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 top-[50%] -z-0">
        <VoiceField
          modes={["lens", "pixels", "ribbons", "lines"]}
          className="h-full w-full"
          ariaLabel="Decorative animated voice waveform"
        />
        <div className="absolute inset-x-0 bottom-0 h-[70px] bg-gradient-to-t from-ink/90 to-transparent" />
      </div>

      <CapabilityStrip />
    </section>
  );
}

const CAPS: { label: string; note: string }[] = [
  { label: "हिन्दी", note: "Hindi" },
  { label: "मराठी", note: "Marathi" },
  { label: "English", note: "English" },
  { label: "Hinglish", note: "Code-mixed" },
  { label: "Voice", note: "Spoken answers" },
  { label: "Tap", note: "One-touch answers" },
];

/** In place of a customer logo row: the languages and answer modes Pramana supports today. */
function CapabilityStrip() {
  return (
    <div className="relative z-10 mt-auto px-[var(--gutter)] pb-[26px]">
      <p className="sr-only">Languages and answer modes Pramana supports</p>
      <ul className="flex items-center justify-between gap-6 overflow-x-auto text-cream [scrollbar-width:none]">
        {CAPS.map((c) => (
          <li key={c.label} className="flex shrink-0 items-center gap-[10px]">
            <span aria-hidden className="grid h-[34px] w-[34px] place-items-center rounded-[9px] border-[1.5px] border-cream/90">
              <span className="h-[10px] w-[10px] rounded-full bg-cream" />
            </span>
            <span className="text-[21px] font-medium tracking-[-0.01em]">{c.label}</span>
            <span className="sr-only">({c.note})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
