"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Wordmark } from "@/components/brand/Wordmark";
import { accountApi, actionKey } from "@/lib/api/account";
import { auth } from "@/lib/api/auth";
import { ApiError, describeError } from "@/lib/api/http";
import { refreshAccount, useAccount } from "@/lib/data/account";
import { setSession } from "@/lib/data/session";

/** Someone was sent an invitation link. They sign in with the invited address and accept. */
export default function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const account = useAccount();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const key = useRef(actionKey("accept"));
  const here = `/invite/${token}`;
  // Whoever is signed in now (possibly after switching accounts) decides what is shown.
  useEffect(() => {
    void refreshAccount();
  }, []);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      const joined = await accountApi.acceptInvitation(token, key.current);
      await refreshAccount();
      router.push(joined.destination);
    } catch (e) {
      setError(e instanceof ApiError ? { code: e.code, message: describeError(e) } : { code: "", message: describeError(e) });
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-ink text-cream">
      <header className="px-6 py-6 sm:px-[50px]">
        <Wordmark />
      </header>
      <main className="mx-auto flex w-full max-w-[560px] flex-1 flex-col justify-center gap-6 px-6 pb-16">
        <h1 className="display-slab text-[clamp(38px,4.4vw,56px)]">You are invited to a Pramana workspace</h1>
        {account.status === "loading" ? (
          <p className="text-cream/60" aria-busy="true">Checking your account...</p>
        ) : account.status !== "ready" ? (
          <>
            <p className="text-[17px] leading-relaxed text-cream/75">Sign in with the email address this invitation was sent to. You come back here afterwards.</p>
            <div>
              <Link href={`/login?next=${encodeURIComponent(here)}`} className="btn-cream">Sign in to accept</Link>
            </div>
          </>
        ) : (
          <>
            <p className="text-[17px] leading-relaxed text-cream/75">
              You are signed in as <strong className="text-cream">{account.account.user.email}</strong>. Accepting adds this workspace to your account with the roles you were given.
            </p>
            {error ? (
              <p role="alert" className="rounded-[14px] border-[0.8px] border-[#ff6b5e]/60 px-4 py-3 text-[15px] text-[#ff8a7f]">{error.message}</p>
            ) : null}
            <div className="flex flex-wrap gap-3">
              <button type="button" className="btn-cream disabled:opacity-50" disabled={busy} onClick={accept}>
                {busy ? "Joining..." : "Accept invitation"}
              </button>
              {error?.code === "INVITATION_EMAIL_MISMATCH" ? (
                <button
                  type="button"
                  className="btn-line"
                  onClick={async () => {
                    await auth.signOut().catch(() => undefined);
                    setSession(null);
                    router.push(`/login?next=${encodeURIComponent(here)}`);
                  }}
                >
                  Use another account
                </button>
              ) : null}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
