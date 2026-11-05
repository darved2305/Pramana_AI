"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { clsx } from "clsx";
import { Wordmark } from "@/components/brand/Wordmark";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#evidence", label: "Evidence" },
  { href: "#workflow", label: "Workflow" },
  { href: "#console", label: "Console" },
];

/** Header measured on the reference: 18px links, centred stacked logo, two outlined buttons. */
export function SiteNav() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <header className="absolute inset-x-0 top-0 z-40 text-cream">
      <div className="relative flex h-[100px] items-start justify-between px-[var(--gutter)] pt-[30px]">
        <nav aria-label="Primary" className="hidden lg:flex items-center gap-[30px] pt-[12px]">
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="group relative pb-[5px] text-[18px] leading-[26px] transition-opacity duration-500 ease-out hover:opacity-100"
            >
              {l.label}
              <span className="absolute inset-x-0 bottom-0 h-px origin-left scale-x-0 bg-current transition-transform duration-500 ease-out group-hover:scale-x-100" />
            </a>
          ))}
        </nav>

        <Link
          href="/"
          aria-label="Pramana home"
          className="absolute left-1/2 top-[24px] -translate-x-1/2 transition-opacity duration-500 hover:opacity-80"
        >
          <Wordmark stacked />
        </Link>

        <div className="ml-auto hidden lg:flex items-center gap-[13px]">
          <Link href="/app" className="btn-line">
            Console
          </Link>
          <Link href="/login" className="btn-line">
            Log in
          </Link>
        </div>

        <button
          type="button"
          className="ml-auto lg:hidden mt-[6px] grid h-11 w-11 place-items-center border-[0.8px] border-cream/80 transition-[border-radius] duration-500 hover:rounded-full"
          aria-expanded={open}
          aria-controls="mobile-menu"
          onClick={() => setOpen(true)}
        >
          <span className="sr-only">Open menu</span>
          <span aria-hidden className="flex flex-col gap-[5px]">
            <span className="block h-px w-5 bg-cream" />
            <span className="block h-px w-5 bg-cream" />
          </span>
        </button>
      </div>

      <div
        id="mobile-menu"
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
        className={clsx(
          "fixed inset-0 z-50 flex flex-col bg-ink px-[var(--gutter)] pb-10 pt-[30px] transition-[opacity,visibility] duration-500 ease-out lg:hidden",
          open ? "visible opacity-100" : "invisible opacity-0",
        )}
      >
        <div className="flex items-start justify-between">
          <Wordmark />
          <button
            type="button"
            className="grid h-11 w-11 place-items-center border-[0.8px] border-cream/80 rounded-full"
            onClick={() => setOpen(false)}
          >
            <span className="sr-only">Close menu</span>
            <span aria-hidden className="relative block h-4 w-4">
              <span className="absolute left-0 top-1/2 h-px w-4 rotate-45 bg-cream" />
              <span className="absolute left-0 top-1/2 h-px w-4 -rotate-45 bg-cream" />
            </span>
          </button>
        </div>
        <nav aria-label="Mobile" className="mt-14 flex flex-col gap-2">
          {LINKS.map((l, i) => (
            <a
              key={l.href}
              href={l.href}
              onClick={() => setOpen(false)}
              className="display-slab text-[44px] text-cream"
              style={{
                transform: open ? "none" : "translateY(16px)",
                opacity: open ? 1 : 0,
                transition: `all .6s cubic-bezier(.22,1,.36,1) ${0.05 * i + 0.1}s`,
              }}
            >
              {l.label}
            </a>
          ))}
        </nav>
        <div className="mt-auto grid grid-cols-2 gap-3">
          <Link href="/app" className="btn-line" onClick={() => setOpen(false)}>
            Console
          </Link>
          <Link href="/login" className="btn-line" onClick={() => setOpen(false)}>
            Log in
          </Link>
        </div>
      </div>
    </header>
  );
}

export function Arrow({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 22 14" className={clsx("arrow h-[12px] w-[20px]", className)} aria-hidden fill="none">
      <path d="M0 7h18M12 1l6 6-6 6" stroke="currentColor" strokeWidth="1.8" />
      <path d="M2 4.5h4M2 9.5h4" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}
