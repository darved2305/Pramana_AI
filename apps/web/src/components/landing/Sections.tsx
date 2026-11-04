"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { motion, useScroll, useTransform, useReducedMotion } from "motion/react";
import { VoiceField, type VoiceMode } from "@/components/voice/VoiceField";
import { BlurText, Reveal } from "@/components/motion/BlurText";
import { Wordmark } from "@/components/brand/Wordmark";
import { Arrow } from "./SiteNav";

/* ------------------------------------------------------------------ */
/* 2. Platform: the dark stadium that grows out of the hero            */
/* ------------------------------------------------------------------ */

export function Platform() {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "center center"] });
  const scale = useTransform(scrollYProgress, [0, 1], reduce ? [1, 1] : [0.86, 1]);
  const radius = useTransform(scrollYProgress, [0, 1], reduce ? ["999px", "999px"] : ["120px", "999px"]);

  return (
    <section id="how" aria-labelledby="platform-title" className="bg-cream text-ink">
      <div className="mx-[var(--rail)] border-x border-[var(--rule-light)] px-[var(--gutter)] pb-[120px] pt-[110px]">
        <BlurText
          as="h2"
          text="The investigator for the physical world"
          className="display-slab mx-auto block max-w-[16ch] text-center text-[clamp(46px,7.7vw,118px)]"
        />
        <div ref={ref} className="mt-[60px]">
          <motion.div
            style={{ scale, borderRadius: radius }}
            className="relative mx-auto aspect-[1280/560] w-full overflow-hidden bg-[#0d0e12] will-change-transform"
          >
            <VoiceField modes={["lines", "pixels"]} hold={5} className="absolute inset-0 h-full w-full" />
          </motion.div>
        </div>
        <Reveal className="mx-auto mt-[64px] max-w-[1100px] text-center">
          <h3 className="display-pixel text-[clamp(26px,3.25vw,50px)]">
            Asks people. Weighs evidence. Knows when it is unsure.
          </h3>
          <p className="mx-auto mt-[28px] max-w-[66ch] text-[clamp(16px,1.3vw,20px)] leading-[1.5]">
            A Wi-Fi outage, a tripped breaker, a dead access point: the cause is somewhere in the building, not in
            a database. Pramana keeps a probability for every possible cause, picks the person and question that
            would settle the decision fastest, and stops to say so when the evidence cannot.
          </p>
        </Reveal>
        <Reveal delay={0.1} className="mt-[52px] grid gap-[40px] sm:grid-cols-2">
          <Link href="/preview/app" className="btn-line lg w-full">
            Explore the console <Arrow />
          </Link>
          <a href="#workflow" className="btn-line lg w-full">
            See the workflow <Arrow />
          </a>
        </Reveal>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* 3. Evidence: sticky headline with four numbered capabilities        */
/* ------------------------------------------------------------------ */

const FEATURES: { title: string; body: string; mode: VoiceMode; tint: string }[] = [
  {
    title: "Sealed before it starts",
    body: "Each investigation publishes a SHA-256 commitment to the hidden fault before a single question is asked. Afterwards anyone can check the diagnosis against it.",
    mode: "pixels",
    tint: "#33a8f5",
  },
  {
    title: "The question worth asking",
    body: "Every candidate question is scored by expected information gain about the decision, against the time it costs the person answering. You can see the runner-ups and why they lost.",
    mode: "lines",
    tint: "#d6f535",
  },
  {
    title: "In the language people speak",
    body: "Questions are spoken and understood in Hindi, Marathi, English and code-mixed Hinglish. A guard can answer by voice, a student by text, an electrician by a single tap.",
    mode: "ribbons",
    tint: "#e535a8",
  },
  {
    title: "Honest about doubt",
    body: "When the evidence cannot settle the decision, Pramana abstains instead of guessing. Repairs need human approval, and a fix only counts once people on site confirm it worked.",
    mode: "lens",
    tint: "#a62be6",
  },
];

export function Evidence() {
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.idx));
        }
      },
      { rootMargin: "-45% 0px -45% 0px" },
    );
    refs.current.forEach((r) => r && io.observe(r));
    return () => io.disconnect();
  }, []);

  return (
    <section id="evidence" aria-labelledby="evidence-title" className="bg-cream text-ink">
      <div className="mx-[var(--rail)] grid border-x border-t border-[var(--rule-light)] lg:grid-cols-2">
        <div className="border-[var(--rule-light)] px-[var(--gutter)] lg:border-r">
          <div className="sticky top-0 flex min-h-[60vh] items-start pt-[100px] lg:min-h-screen">
            <BlurText
              as="h2"
              text="Every answer becomes evidence"
              className="display-slab block max-w-[9ch] text-[clamp(52px,7.7vw,118px)]"
            />
          </div>
        </div>
        <div className="relative px-[var(--gutter)]">
          <ol
            aria-hidden
            className="display-pixel pointer-events-none sticky top-[100px] z-10 float-right hidden flex-col items-end gap-[12px] pt-[100px] text-[34px] lg:flex"
          >
            {FEATURES.map((_, i) => (
              <li key={i} className={clsx("transition-colors duration-500", i === active ? "text-ink" : "text-ink/15")}>
                {i + 1}
              </li>
            ))}
          </ol>
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              ref={(el) => {
                refs.current[i] = el;
              }}
              data-idx={i}
              className="flex min-h-[80vh] flex-col justify-center py-[60px] lg:pr-[90px]"
            >
              <Reveal y={80} rotate={-14}>
                <ScanlineCard mode={f.mode} tint={f.tint} />
                <h3 className="display-pixel mt-[36px] text-[clamp(28px,3.25vw,50px)]">{f.title}</h3>
                <p className="mt-[18px] max-w-[46ch] text-[18px] leading-[1.55] text-ink/80">{f.body}</p>
              </Reveal>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** Black card with horizontal scanlines over a voice visual, echoing the reference's striped illustrations. */
function ScanlineCard({ mode, tint }: { mode: VoiceMode; tint: string }) {
  return (
    <div className="relative aspect-square w-full max-w-[340px] overflow-hidden rounded-[10px] bg-black">
      <VoiceField modes={[mode]} className="absolute inset-0 h-full w-full" />
      <div
        aria-hidden
        className="absolute inset-0 mix-blend-multiply"
        style={{ background: `repeating-linear-gradient(0deg, transparent 0 5px, rgba(0,0,0,.85) 5px 9px)` }}
      />
      <div aria-hidden className="absolute inset-0 opacity-25" style={{ background: `radial-gradient(circle at 30% 30%, ${tint}, transparent 60%)` }} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 4. Dark platform section with the tile wall (reference order)       */
/* ------------------------------------------------------------------ */

// Solid tile colours sampled from the reference's tile wall.
const TILE = ["#1de9d0", "#ff5a1f", "#a62be6"];

export function Workflow() {
  return (
    <section id="workflow" aria-labelledby="workflow-title" className="overflow-hidden bg-ink text-cream">
      <div className="px-[var(--gutter)] pb-[60px] pt-[120px]">
        <BlurText
          as="h2"
          text="One loop from complaint to verified fix"
          className="display-slab mx-auto block max-w-[15ch] text-center text-[clamp(46px,7.7vw,118px)]"
        />
        <Reveal className="mx-auto mt-[40px] max-w-[1090px] text-center">
          <p className="text-[clamp(16px,1.3vw,20px)] leading-[1.5]">
            A report becomes a belief over every possible cause. Each question goes to the person who can settle the
            decision fastest, each answer updates the belief, and any repair waits for human approval before people on
            site confirm it worked. If it did not, the investigation reopens on its own.
          </p>
          <div className="mt-[34px] flex flex-wrap justify-center gap-[20px]">
            <Link href="/preview/app" className="btn-line lg">
              Try the preview <Arrow />
            </Link>
            <a href="#console" className="btn-line lg">
              See the console <Arrow />
            </a>
          </div>
        </Reveal>
      </div>
      <TileWall />
    </section>
  );
}

/** Columns of square tiles rising like an equaliser, as on the reference's dark section. */
function TileWall() {
  const ref = useRef<HTMLDivElement>(null);
  const [t, setT] = useState(0);
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let visible = false;
    const start = performance.now();
    const loop = () => {
      if (!visible) {
        timer = undefined;
        return;
      }
      setT((performance.now() - start) / 1000);
      timer = setTimeout(loop, 140);
    };
    const io = new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      if (visible && !timer) loop();
    });
    if (ref.current) io.observe(ref.current);
    return () => {
      io.disconnect();
      visible = false;
      if (timer) clearTimeout(timer);
    };
  }, [reduce]);

  const cols = 16;
  const rows = 8;
  return (
    <div ref={ref} aria-hidden className="mx-auto grid max-w-[1536px] grid-cols-[repeat(16,1fr)] gap-[1.4vw] px-[var(--gutter)] pb-[40px]">
      {Array.from({ length: cols }, (_, c) => {
        const h = Math.round(2 + 6 * (0.5 + 0.5 * Math.sin(c * 0.9 + t * 1.6) * Math.cos(c * 0.37 - t * 0.7)));
        return (
          <div key={c} className="flex flex-col justify-end gap-[1vw]" style={{ height: `min(${rows * 3.9}vw, ${rows * 60}px)` }}>
            {Array.from({ length: h }, (_, r) => {
              const glyph = (c * 7 + r * 3) % 5 === 0;
              const color = TILE[(c + Math.floor(r / 2)) % 3];
              const size = 0.42 + (0.3 * (r + 1)) / h;
              return (
                <span
                  key={r}
                  className="mx-auto grid aspect-square place-items-center transition-all duration-300"
                  style={{ width: `${size * 100}%`, background: glyph ? "#f4efe6" : color, borderRadius: glyph ? 4 : 0 }}
                >
                  {glyph ? <span className="display-pixel text-[1.2vw] leading-none text-ink">{"PRAMANA"[(c + r) % 7]}</span> : null}
                </span>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 5. Numeral built from tiles, with the capability list card          */
/* ------------------------------------------------------------------ */

// 5x7 bitmaps for the digits used in the numeral.
const DIGITS: Record<string, string[]> = {
  "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
  "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
};

const CONSOLE_PARTS = [
  { t: "Competing causes", d: "Every hypothesis with its probability, plus the open-world row." },
  { t: "Why this question", d: "Information gain, cost and the alternatives that lost." },
  { t: "Evidence ledger", d: "Every observation with source, place, time and doubt." },
  { t: "Contradictions", d: "Answers that disagree, side by side." },
  { t: "Approvals", d: "Proposed repairs with risk and reversibility." },
  { t: "Replay", d: "Step through the event log to see belief change." },
];

export function ConsolePreview() {
  return (
    <section id="console" aria-labelledby="console-title" className="bg-ink text-cream">
      <div className="grid gap-[60px] px-[var(--gutter)] pb-[140px] pt-[40px] lg:grid-cols-2">
        <div className="flex flex-col">
          <TileNumeral value="10" />
          <Reveal className="mt-auto pt-[60px]">
            <h2 id="console-title" className="sr-only">
              Ten languages, one console that shows its work
            </h2>
            <p className="max-w-[600px] text-[clamp(16px,1.25vw,19px)] leading-[1.6]">
              Pramana listens for answers in 10 Indian languages and asks its questions in English, Hindi, Marathi or
              Hinglish. In the console, every step is laid out next to the reasoning behind it: nothing hides behind a
              single confidence score.
            </p>
            <Link href="/preview/app" className="btn-line lg mt-[40px]">
              Explore the console <Arrow />
            </Link>
          </Reveal>
        </div>
        <Reveal delay={0.1} className="self-end rounded-[16px] bg-[#0b0508] px-[28px] py-[12px] sm:px-[70px]">
          <ul>
            {CONSOLE_PARTS.map((p, i) => (
              <li key={p.t} className="group flex items-center gap-[30px] border-b border-white/25 py-[12px] last:border-none">
                <span
                  aria-hidden
                  className="relative grid h-[60px] w-[60px] shrink-0 place-items-center overflow-hidden rounded-[8px] transition-transform duration-500 ease-out group-hover:-rotate-6"
                  style={{ background: [TILE[2], TILE[1], TILE[0], "#d6f535", "#33a8f5", "#e535a8"][i] }}
                >
                  <span className="absolute inset-0" style={{ background: "repeating-radial-gradient(circle at 30% 30%, transparent 0 5px, rgba(0,0,0,.35) 5px 7px)" }} />
                  <span className="display-pixel relative text-[24px] text-black">{p.t[0]}</span>
                </span>
                <span>
                  <span className="block text-[clamp(20px,1.85vw,28px)] leading-tight">{p.t}</span>
                  <span className="mt-0.5 block text-[14px] text-cream/55">{p.d}</span>
                </span>
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </section>
  );
}

/** Large numeral assembled from square tiles that fly into place when it scrolls into view. */
function TileNumeral({ value }: { value: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(false);
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce) return;
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setOn(true), { threshold: 0.3 });
    if (ref.current) io.observe(ref.current);
    return () => io.disconnect();
  }, [reduce]);
  const shown = on || reduce;
  const glyphs = value.split("").map((d) => DIGITS[d]);
  return (
    <div ref={ref} aria-hidden className="flex gap-[clamp(14px,2.6vw,40px)]">
      {glyphs.map((g, gi) => (
        <div key={gi} className="grid grid-cols-5">
          {g.flatMap((row, r) =>
            row.split("").map((bit, c) => {
              const k = gi * 100 + r * 5 + c;
              const dx = Math.round(Math.sin(k * 12.9) * 180);
              const dy = Math.round(120 + Math.cos(k * 7.3) * 160);
              return (
                <span
                  key={`${r}-${c}`}
                  className="aspect-square w-[clamp(18px,2.8vw,43px)]"
                  style={{
                    background: bit === "1" ? TILE[(r + c + gi) % 3] : "transparent",
                    opacity: bit === "1" && shown ? 1 : 0,
                    transform: shown ? "none" : `translate(${dx}px, ${dy}px) rotate(${Math.round(dx / 4)}deg)`,
                    transition: `transform 1.1s cubic-bezier(.22,1,.36,1) ${((k % 17) * 0.03).toFixed(2)}s, opacity .6s ease ${((k % 17) * 0.03).toFixed(2)}s`,
                  }}
                />
              );
            }),
          )}
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 5b. Two editorial cards (reference: article cards with VIEW ALL)    */
/* ------------------------------------------------------------------ */

const NOTES: { title: string; body: string; mode: VoiceMode }[] = [
  {
    title: "Why a sealed fault keeps the AI honest",
    body: "Before the first question, the core publishes a hash of the hidden fault. After the reveal anyone can check that the diagnosis was judged against what was really broken.",
    mode: "pixels",
  },
  {
    title: "When the right answer is: not sure yet",
    body: "If the evidence cannot separate the remaining causes, or the cause may be outside the model, Pramana abstains and says what would settle it. A wrong repair costs more than a question.",
    mode: "ribbons",
  },
];

export function Notes() {
  return (
    <section aria-labelledby="notes-title" className="bg-cream text-ink">
      <h2 id="notes-title" className="sr-only">
        How Pramana thinks
      </h2>
      <div className="mx-[var(--rail)] border-x border-[var(--rule-light)]">
        <div className="grid sm:grid-cols-2">
          {NOTES.map((n, i) => (
            <Reveal key={n.title} delay={i * 0.08} className={clsx("px-[var(--gutter)] py-[60px]", i === 0 && "sm:border-r sm:border-[var(--rule-light)]")}>
              <Link href="/preview/app" className="group block">
                <div className="relative aspect-[573/320] overflow-hidden rounded-[10px] bg-ink">
                  <VoiceField modes={[n.mode]} className="absolute inset-0 h-full w-full transition-transform duration-700 ease-out group-hover:scale-[1.03]" />
                </div>
                <p className="mt-[28px] text-[14px] text-ink/45">Explainer</p>
                <h3 className="display-pixel mt-[18px] text-[clamp(26px,2.6vw,42px)]">{n.title}</h3>
                <p className="mt-[22px] text-[18px] leading-[1.6] text-ink/80">{n.body}</p>
              </Link>
            </Reveal>
          ))}
        </div>
        <div className="flex justify-center pb-[30px]">
          <Link href="/preview/app" className="btn-line">
            View all <Arrow />
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* 6. Closing call to action with the circle strip                     */
/* ------------------------------------------------------------------ */

export function ClosingCta() {
  return (
    <section aria-labelledby="cta-title" className="overflow-hidden bg-cream text-ink">
      <div className="mx-[var(--rail)] border-x border-[var(--rule-light)] px-[var(--gutter)] pb-[60px] pt-[120px] text-center">
        <BlurText
          as="h2"
          text="Find out what is actually wrong"
          className="display-slab mx-auto block max-w-[13ch] text-[clamp(46px,7.7vw,118px)]"
        />
        <Reveal>
          <p className="mx-auto mt-[36px] max-w-[54ch] text-[clamp(16px,1.3vw,20px)] leading-[1.5]">
            Start an investigation against the local core, or open the preview to explore every screen with clearly
            marked sample data.
          </p>
          <div className="mt-[30px] flex flex-wrap justify-center gap-[13px]">
            <Link href="/app/investigations/new" className="btn-line lg">
              Start an investigation <Arrow />
            </Link>
            <Link href="/preview/app" className="btn-line lg">
              Open the preview <Arrow />
            </Link>
          </div>
        </Reveal>
      </div>
      <CircleStrip />
    </section>
  );
}

function CircleStrip() {
  const items: { mode: VoiceMode | null; half?: "l" | "r" }[] = [
    { mode: "pixels" },
    { mode: null, half: "r" },
    { mode: null, half: "l" },
    { mode: "ribbons" },
    { mode: null, half: "r" },
    { mode: null, half: "l" },
    { mode: "lines" },
  ];
  return (
    <div aria-hidden className="flex w-full justify-center overflow-hidden">
      <div className="flex shrink-0">
        {items.map((it, i) => (
          <div
            key={i}
            className={clsx(
              "relative aspect-square w-[clamp(140px,24vw,370px)] shrink-0 overflow-hidden bg-ink",
              it.half === "r" && "w-[clamp(70px,12vw,185px)] aspect-[1/2] rounded-l-full",
              it.half === "l" && "w-[clamp(70px,12vw,185px)] aspect-[1/2] rounded-r-full",
              !it.half && "rounded-full",
            )}
          >
            {it.mode ? <VoiceField modes={[it.mode]} className="absolute inset-0 h-full w-full" /> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 7. Footer                                                           */
/* ------------------------------------------------------------------ */

export function SiteFooter() {
  return (
    <footer className="bg-ink text-cream">
      <div className="mx-[var(--rail)] border-x border-[var(--rule-dark)]">
        <div className="h-[90px] border-b border-[var(--rule-dark)]" />
        <div className="grid border-b border-[var(--rule-dark)] lg:grid-cols-[1fr_340px]">
          <div className="px-[var(--gutter)] py-[64px] lg:border-r lg:border-[var(--rule-dark)]">
            <Wordmark />
            <p className="display-slab mt-[44px] text-[clamp(44px,5.86vw,96px)]">
              Evidence from
              <br />
              the physical world
            </p>
            <div className="mt-[52px] grid gap-[20px] sm:grid-cols-2 sm:gap-[50px] lg:max-w-[684px]">
              <Link href="/preview/app" className="btn-line lg">
                Preview <Arrow />
              </Link>
              <Link href="/login" className="btn-line lg">
                Log in <Arrow />
              </Link>
            </div>
          </div>
          <div className="flex flex-col justify-between px-[var(--gutter)] py-[64px]">
            <nav aria-label="Footer" className="display-pixel flex flex-col gap-[14px] text-[clamp(30px,2.6vw,42px)]">
              <a href="#how" className="transition-opacity duration-500 hover:opacity-60">How</a>
              <a href="#workflow" className="transition-opacity duration-500 hover:opacity-60">Workflow</a>
              <Link href="/app" className="transition-opacity duration-500 hover:opacity-60">Console</Link>
            </nav>
            <Link href="/app/settings" className="btn-line lg mt-[52px] self-start">
              Settings <Arrow />
            </Link>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-4 px-[var(--gutter)] py-[30px] text-[13px] text-cream/50">
          <span>Pramana. Copyright {new Date().getFullYear()}.</span>
          <span>Voice powered by Gnani.ai</span>
        </div>
      </div>
    </footer>
  );
}

export function FloatingPreview() {
  // On the reference the floating pill appears only once the hero has scrolled away.
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const on = () => setShown(window.scrollY > window.innerHeight * 0.6);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <Link
      href="/preview/app"
      tabIndex={shown ? 0 : -1}
      aria-hidden={!shown}
      className={clsx(
        "display-pixel fixed bottom-[22px] right-[22px] z-30 rounded-full border border-ink/80 bg-cream px-[18px] py-[12px] text-[22px] leading-none text-ink shadow-[0_6px_30px_rgba(0,0,0,.18)] transition-[transform,opacity] duration-500 ease-out hover:-translate-y-[2px]",
        shown ? "opacity-100" : "pointer-events-none translate-y-3 opacity-0",
      )}
    >
      Preview
    </Link>
  );
}
