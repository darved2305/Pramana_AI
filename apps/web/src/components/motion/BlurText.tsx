"use client";

import { useEffect, useMemo, useRef, useState, type ElementType } from "react";
import { clsx } from "clsx";
import { usePrefersReducedMotion } from "@/lib/hooks/useReducedMotion";

/**
 * Letter-by-letter reveal observed on the reference headlines: each glyph starts blurred
 * and transparent, then sharpens in a scattered order (not left to right).
 * Timings are estimates from frame captures: ~0.9s per glyph, spread over ~1.1s.
 *
 * The full text is always in the DOM for screen readers; the animated glyphs are hidden
 * from assistive technology.
 */
export function BlurText({
  text,
  as: Tag = "span",
  className,
  trigger = "view",
  delay = 0,
  spread = 1.1,
}: {
  text: string;
  as?: ElementType;
  className?: string;
  trigger?: "load" | "view";
  delay?: number;
  spread?: number;
}) {
  const ref = useRef<HTMLElement>(null);
  const reduced = usePrefersReducedMotion();
  const [on, setOn] = useState(false);

  const words = useMemo(() => {
    let i = 0;
    return text.split(" ").map((w) =>
      Array.from(w).map((ch) => {
        const n = i++;
        // Deterministic scatter so server and client agree.
        const r = (Math.sin(n * 12.9898 + text.length * 78.233) * 43758.5453) % 1;
        return { ch, d: Math.round(Math.abs(r) * spread * 100) / 100 };
      }),
    );
  }, [text, spread]);

  useEffect(() => {
    if (reduced) return;
    if (trigger === "load") {
      const id = requestAnimationFrame(() => setOn(true));
      return () => cancelAnimationFrame(id);
    }
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setOn(true);
          io.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [trigger, reduced]);

  const shown = on || reduced;

  return (
    <Tag ref={ref} className={clsx(className)}>
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        {words.map((word, wi) => (
          <span key={wi} className="inline-block whitespace-nowrap">
            {word.map((g, gi) => (
              <span
                key={gi}
                className="inline-block will-change-[filter,opacity]"
                style={{
                  opacity: shown ? 1 : 0,
                  filter: shown ? "blur(0px)" : "blur(14px)",
                  transition: reduced
                    ? "none"
                    : `opacity 0.9s cubic-bezier(.22,1,.36,1) ${delay + g.d}s, filter 0.9s cubic-bezier(.22,1,.36,1) ${delay + g.d}s`,
                }}
              >
                {g.ch}
              </span>
            ))}
            {wi < words.length - 1 ? <span className="inline-block">&nbsp;</span> : null}
          </span>
        ))}
      </span>
    </Tag>
  );
}

/** Fades and lifts a block into place when it enters the viewport. */
export function Reveal({
  children,
  className,
  delay = 0,
  y = 24,
  rotate = 0,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
  y?: number;
  /** Starting rotation in degrees; the reference's feature cards swing in from about -14deg. */
  rotate?: number;
  as?: ElementType;
}) {
  const ref = useRef<HTMLElement>(null);
  const reduced = usePrefersReducedMotion();
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (reduced) return;
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setOn(true);
          io.disconnect();
        }
      },
      { threshold: 0.2 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reduced]);
  const shown = on || reduced;
  return (
    <Tag
      ref={ref}
      className={className}
      style={{
        opacity: shown ? 1 : 0,
        transform: shown ? "none" : `translateY(${y}px) rotate(${rotate}deg)`,
        transformOrigin: "left bottom",
        transition: reduced
          ? "none"
          : `opacity .9s cubic-bezier(.22,1,.36,1) ${delay}s, transform .9s cubic-bezier(.22,1,.36,1) ${delay}s`,
      }}
    >
      {children}
    </Tag>
  );
}
