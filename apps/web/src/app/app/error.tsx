"use client";

import { useEffect } from "react";
import { Button, ButtonLink, Card } from "@/components/ui";
import { IconAlert } from "@/components/ui/icons";

export default function ConsoleError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <Card className="mt-6 flex flex-col items-center px-6 py-14 text-center" role="alert">
      <div className="mb-4 grid h-12 w-12 place-items-center rounded-[12px] bg-bad/12 text-bad">
        <IconAlert />
      </div>
      <h1 className="font-serif text-[30px]">This screen failed to load</h1>
      <p className="mt-2 max-w-[48ch] text-[14px] text-muted">An unexpected error stopped this screen. The rest of the console still works.</p>
      {error.digest ? <p className="mt-2 font-mono text-[11px] text-muted">ref {error.digest}</p> : null}
      <div className="mt-6 flex gap-2">
        <Button variant="primary" onClick={reset}>
          Try again
        </Button>
        <ButtonLink href="/app">Overview</ButtonLink>
      </div>
    </Card>
  );
}
