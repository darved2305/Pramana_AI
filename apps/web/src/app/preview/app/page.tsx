"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { previewMode } from "@/lib/store/local";

/**
 * Turns on preview mode for this browser tab and opens the console. Preview mode only
 * swaps data sources for labelled fixtures; it is not a sign-in and grants nothing.
 */
export default function PreviewEntry() {
  const router = useRouter();
  useEffect(() => {
    previewMode.enable();
    router.replace("/app");
  }, [router]);
  return (
    <div className="app-root grid min-h-dvh place-items-center text-[14px] text-muted" aria-live="polite">
      Opening the development preview...
    </div>
  );
}
