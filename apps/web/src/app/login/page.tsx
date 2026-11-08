"use client";

import { PREVIEW_ENABLED } from "@/lib/store/local";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useRef, useState } from "react";
import { clsx } from "clsx";
import { Wordmark } from "@/components/brand/Wordmark";
import { VoiceField } from "@/components/voice/VoiceField";
import { BlurText } from "@/components/motion/BlurText";
import { auth, validateEmail, validatePassword } from "@/lib/api/auth";
import { describeError } from "@/lib/api/http";
import { setSession } from "@/lib/data/session";
import { refreshAccount } from "@/lib/data/account";
import { IconEye, IconEyeOff } from "@/components/ui/icons";

/** Only same-site paths are followed after sign-in, never another origin. */
function nextPath(): string {
  const n = new URLSearchParams(window.location.search).get("next") ?? "";
  return n.startsWith("/") && !n.startsWith("//") ? n : "/app";
}

/** Google's "G" mark, as its sign-in branding guidelines ask for on the button. */
function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}

function LoginInner() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [touched, setTouched] = useState({ email: false, password: false });
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState<"password" | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const params = useSearchParams();
  // The core returns here with a reason when Google sign-in did not finish.
  const reason = params.get("error");
  const googleError =
    reason === "cancelled"
      ? "Google sign-in was cancelled. You can try again."
      : reason
        ? "Google sign-in did not finish. Please try again."
        : null;
  const nextParam = params.get("next") ?? "";
  const googleHref = `/api/core/v1/auth/google/start?next=${encodeURIComponent(
    nextParam.startsWith("/") && !nextParam.startsWith("//") ? nextParam : "/app",
  )}`;
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
      await refreshAccount(); // a different person may have been signed in before
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
          <p className="mt-3 text-[16px] leading-relaxed text-cream/70">
            Welcome back. New to Pramana? Continue with Google and you will set up your workspace in a few steps.
          </p>

          {googleError ? (
            <p role="alert" className="mt-6 rounded-[14px] border-[0.8px] border-[#ff6b5e]/60 px-4 py-3 text-[14px] text-[#ff8a7f]">
              {googleError}
            </p>
          ) : null}
          <a
            href={googleHref}
            className="mt-8 flex h-[52px] w-full items-center justify-center gap-3 rounded-full bg-cream text-[16px] font-medium text-ink transition-[filter] duration-300 hover:brightness-95"
          >
            <GoogleMark />
            Continue with Google
          </a>
          <div className="mt-7 flex items-center gap-3 text-[12px] uppercase tracking-[0.08em] text-cream/45" aria-hidden>
            <span className="h-px flex-1 bg-cream/20" />
            or with email
            <span className="h-px flex-1 bg-cream/20" />
          </div>

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

        <p className="text-[12px] text-cream/40">Email sign-in is for accounts your site operator set up.</p>
      </main>
    </div>
  );
}

function Spin() {
  return <span aria-hidden className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" />;
}
