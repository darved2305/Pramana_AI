"use client";

import { useSyncExternalStore } from "react";

/**
 * True when the OS asks for reduced motion, or when the user turned motion off in
 * Pramana's settings (stored as `data-motion="reduce"` on <html>).
 */
function subscribe(cb: () => void) {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", cb);
  const mo = new MutationObserver(cb);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-motion"] });
  return () => {
    mq.removeEventListener("change", cb);
    mo.disconnect();
  };
}

function read() {
  return (
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    document.documentElement.dataset.motion === "reduce"
  );
}

export function usePrefersReducedMotion() {
  return useSyncExternalStore(subscribe, read, () => false);
}
