"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { clsx } from "clsx";
import { Wordmark } from "@/components/brand/Wordmark";
import { VoiceField } from "@/components/voice/VoiceField";
import { BlurText } from "@/components/motion/BlurText";
import { auth, validateEmail, validatePassword, AuthUnavailableError } from "@/lib/api/auth";
import { IconEye, IconEyeOff } from "@/components/ui/icons";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [touched, setTouched] = useState({ email: false, password: false });
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState<"password" | "google" | null>(null);
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
      await auth.signInWithPassword(email.trim(), password);
    } catch (x) {
      setFormError(x instanceof AuthUnavailableError ? x.message : "Sign-in failed. Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const google = async () => {
    setFormError(null);
    setBusy("google");
    try {
      await auth.signInWithGoogle();
    } catch (x) {
      setFormError(x instanceof AuthUnavailableError ? x.message : "Sign-in failed. Please try again.");
    } finally {
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

          <button
            type="button"
            onClick={google}
            disabled={busy !== null}
            className="btn-line mt-9 w-full gap-3 normal-case tracking-normal disabled:opacity-50"
            style={{ fontSize: 15, fontWeight: 500 }}
          >
            {busy === "google" ? <Spin /> : <GoogleMark />}
            Continue with Google
          </button>

          <div className="my-7 flex items-center gap-4 text-[12px] uppercase tracking-[0.12em] text-cream/40" aria-hidden>
            <span className="h-px flex-1 bg-cream/15" /> or <span className="h-px flex-1 bg-cream/15" />
          </div>

          <form onSubmit={submit} noValidate className="flex flex-col gap-5" aria-describedby={formError ? "form-error" : undefined}>
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
                {formError}{" "}
                <Link href="/preview/app" className="font-medium underline underline-offset-4">
                  Open the preview
                </Link>
              </div>
            ) : null}

            <button type="submit" disabled={busy !== null} className="btn-line lg mt-2 w-full bg-cream !text-ink hover:bg-cream/90 disabled:opacity-60">
              {busy === "password" ? <Spin /> : null}
              Log in
            </button>
          </form>

          <p className="mt-8 text-[14px] text-cream/60">
            Just exploring?{" "}
            <Link href="/preview/app" className="text-cream underline underline-offset-4 hover:no-underline">
              Open the development preview
            </Link>{" "}
            with sample data. It is not a sign-in.
          </p>
        </div>

        <p className="text-[12px] text-cream/40">Pramana. Sign-in is not connected to a backend yet.</p>
      </main>
    </div>
  );
}

function Spin() {
  return <span aria-hidden className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" />;
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" aria-hidden>
      <path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.3-1.6 3.8-5.5 3.8-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.8 1.5l2.6-2.5C16.8 3.2 14.6 2.2 12 2.2 6.6 2.2 2.2 6.6 2.2 12s4.4 9.8 9.8 9.8c5.7 0 9.4-4 9.4-9.6 0-.6-.1-1.1-.2-1.6H12z" />
    </svg>
  );
}
