"use client";

import { PREVIEW_ENABLED } from "@/lib/store/local";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { clsx } from "clsx";
import { Wordmark } from "@/components/brand/Wordmark";
import { VoiceField } from "@/components/voice/VoiceField";
import { BlurText } from "@/components/motion/BlurText";
import { auth, validateEmail, validatePassword } from "@/lib/api/auth";
import { describeError } from "@/lib/api/http";
import { setSession } from "@/lib/data/session";
import { IconEye, IconEyeOff } from "@/components/ui/icons";

/** Only same-site paths are followed after sign-in, never another origin. */
function nextPath(): string {
  const n = new URLSearchParams(window.location.search).get("next") ?? "";
  return n.startsWith("/") && !n.startsWith("//") ? n : "/app";
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [touched, setTouched] = useState({ email: false, password: false });
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState<"password" | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const pwRef = useRef<HTMLInputElement>(null);

  const eErr = validateEmail(email);
  const pErr = validatePassword(password);
  const showE = (touched.email || submitted) && eErr;
  const showP = (touched.password || submitted) && pErr;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitted(true);
    setFormError(null);
    if (eErr) return emailRef.current?.focus();
    if (pErr) return pwRef.current?.focus();
    setBusy("password");
    try {
      setSession(await auth.signInWithPassword(email.trim(), password));
      router.replace(nextPath());
    } catch (x) {
      setFormError(describeError(x));
      setBusy(null);
    }
  };

  return (
    <div className="grid min-h-dvh bg-ink text-cream lg:grid-cols-[1.05fr_1fr]">
      {/* Visual half */}
      <aside className="relative hidden overflow-hidden border-r border-[var(--rule-dark)] lg:flex lg:flex-col">
        <div className="relative z-10 px-[50px] pt-[30px]">
          <Link href="/" aria-label="Pramana home" className="inline-block transition-opacity duration-500 hover:opacity-80">
            <Wordmark />
          </Link>
        </div>
        <div className="relative z-10 px-[50px] pt-[12vh]">
          <BlurText as="p" trigger="load" text="Evidence from the physical world" className="display-slab block max-w-[11ch] text-[clamp(48px,5vw,84px)]" />
        </div>
        <div className="absolute inset-x-0 bottom-0 top-[42%]">
          <VoiceField modes={["lens"]} className="h-full w-full" ariaLabel="Decorative animated voice waveform" />
        </div>
      </aside>

      {/* Form half */}
      <main className="flex flex-col px-6 py-8 sm:px-[50px]">
        <div className="flex items-center justify-between">
          <Link href="/" aria-label="Pramana home" className="lg:invisible">
            <Wordmark />
          </Link>
          <Link href="/" className="btn-line">
            Back to site
          </Link>
        </div>

        <div className="mx-auto flex w-full max-w-[420px] flex-1 flex-col justify-center py-12">
          <h1 className="display-slab text-[clamp(44px,4.4vw,64px)]">Log in</h1>
          <p className="mt-3 text-[16px] leading-relaxed text-cream/70">Welcome back. Sign in to open the Pramana console.</p>

          <form onSubmit={submit} noValidate className="mt-9 flex flex-col gap-5" aria-describedby={formError ? "form-error" : undefined}>
            <div className="flex flex-col gap-2">
              <label htmlFor="email" className="text-[13px] font-medium uppercase tracking-[0.06em] text-cream/70">
                Email
              </label>
              <input
                ref={emailRef}
                id="email"
                type="email"
                autoComplete="email"
                inputMode="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onBlur={() => setTouched((t) => ({ ...t, email: true }))}
                aria-invalid={Boolean(showE)}
                aria-describedby={showE ? "email-err" : undefined}
                placeholder="you@example.com"
                className={clsx(
                  "h-[52px] w-full border-[0.8px] bg-transparent px-4 text-[16px] text-cream outline-none transition-[border-color,border-radius] duration-500 ease-out placeholder:text-cream/35 focus:rounded-[26px]",
                  showE ? "border-[#ff6b5e]" : "border-cream/40 hover:border-cream/70 focus:border-cream",
                )}
              />
              {showE ? (
                <p id="email-err" className="text-[13px] text-[#ff8a7f]">
                  {eErr}
                </p>
              ) : null}
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <label htmlFor="password" className="text-[13px] font-medium uppercase tracking-[0.06em] text-cream/70">
                  Password
                </label>
                <button
                  type="button"
                  className="text-[13px] text-cream/60 underline-offset-4 hover:text-cream hover:underline"
                  onClick={async () => {
                    setFormError(null);
                    if (eErr) {
                      setTouched((t) => ({ ...t, email: true }));
                      return emailRef.current?.focus();
                    }
                    try {
                      await auth.requestPasswordReset(email.trim());
                    } catch (x) {
                      setFormError(x instanceof Error ? x.message : "Could not send a reset link.");
                    }
                  }}
                >
                  Forgot password?
                </button>
              </div>
              <div className="relative">
                <input
                  ref={pwRef}
                  id="password"
                  type={show ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onBlur={() => setTouched((t) => ({ ...t, password: true }))}
                  aria-invalid={Boolean(showP)}
                  aria-describedby={showP ? "pw-err" : undefined}
                  className={clsx(
                    "h-[52px] w-full border-[0.8px] bg-transparent pl-4 pr-12 text-[16px] text-cream outline-none transition-[border-color,border-radius] duration-500 ease-out focus:rounded-[26px]",
                    showP ? "border-[#ff6b5e]" : "border-cream/40 hover:border-cream/70 focus:border-cream",
                  )}
                />
                <button
                  type="button"
                  onClick={() => setShow((s) => !s)}
                  aria-label={show ? "Hide password" : "Show password"}
                  aria-pressed={show}
                  className="absolute right-3 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center text-cream/60 hover:text-cream"
                >
                  {show ? <IconEyeOff /> : <IconEye />}
                </button>
              </div>
              {showP ? (
                <p id="pw-err" className="text-[13px] text-[#ff8a7f]">
                  {pErr}
                </p>
              ) : null}
            </div>

            {formError ? (
              <div id="form-error" role="alert" className="border-[0.8px] border-[#f5b335]/50 bg-[#f5b335]/[.07] px-4 py-3 text-[14px] leading-relaxed text-[#f7c96b]">
                {formError}
                {PREVIEW_ENABLED ? (
                  <>
                    {" "}
                    <Link href="/preview/app" className="font-medium underline underline-offset-4">
                      Open the preview
                    </Link>
                  </>
                ) : null}
              </div>
            ) : null}

            <button type="submit" disabled={busy !== null} className="btn-line lg mt-2 w-full bg-cream !text-ink hover:bg-cream/90 disabled:opacity-60">
              {busy === "password" ? <Spin /> : null}
              Log in
            </button>
          </form>

          {PREVIEW_ENABLED ? (
            <p className="mt-8 text-[14px] text-cream/60">
              Just exploring?{" "}
              <Link href="/preview/app" className="text-cream underline underline-offset-4 hover:no-underline">
                Open the development preview
              </Link>{" "}
              with sample data. It is not a sign-in.
            </p>
          ) : null}
        </div>

        <p className="text-[12px] text-cream/40">Pramana. Accounts are created by your site operator.</p>
      </main>
    </div>
  );
}

function Spin() {
  return <span aria-hidden className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" />;
}
