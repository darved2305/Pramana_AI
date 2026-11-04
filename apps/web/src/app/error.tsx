"use client";

import Link from "next/link";
import { useEffect } from "react";

export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center bg-ink px-6 text-center text-cream" role="alert">
      <h1 className="display-slab text-[clamp(36px,4.5vw,64px)]">Something went wrong</h1>
      <p className="mt-4 max-w-[46ch] text-[17px] leading-relaxed text-cream/70">
        This screen hit an unexpected error. Nothing you entered was sent anywhere because of it.
      </p>
      {error.digest ? <p className="mt-2 font-mono text-[12px] text-cream/40">ref {error.digest}</p> : null}
      <div className="mt-8 flex gap-[13px]">
        <button type="button" onClick={reset} className="btn-line lg">
          Try again
        </button>
        <Link href="/" className="btn-line lg">
          Home
        </Link>
      </div>
    </main>
  );
}
