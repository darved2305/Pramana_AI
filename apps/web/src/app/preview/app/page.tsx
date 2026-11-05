"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { PREVIEW_ENABLED, previewMode } from "@/lib/store/local";

/**
 * Turns on preview mode for this browser tab and opens the console. Preview mode only
 * swaps data sources for labelled fixtures; it is not a sign-in and grants nothing.
 */
export default function PreviewEntry() {
  const router = useRouter();
  useEffect(() => {
    if (!PREVIEW_ENABLED) {
      // The product has no sample-data mode: send people to the live console.
      router.replace("/login");
      return;
    }
    previewMode.enable();
    router.replace("/app");
  }, [router]);
  return (
    <div className="app-root grid min-h-dvh place-items-center text-[14px] text-muted" aria-live="polite">
      {PREVIEW_ENABLED ? "Opening the development preview..." : "Opening the console..."}
    </div>
  );
}
