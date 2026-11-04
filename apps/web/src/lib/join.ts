/**
 * Participant links. The core issues a per-participant token (API guide, section 2); the
 * link carries it together with the investigation, participant and scenario IDs the
 * participant page needs, encoded as one URL-safe segment: /join/<segment>.
 */
export interface JoinPayload {
  i: string; // investigation id
  p: string; // participant id
  s: string; // scenario id
  t: string; // participant token
}

export function encodeJoin(p: JoinPayload): string {
  const json = JSON.stringify(p);
  const b64 = btoa(unescape(encodeURIComponent(json)));
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function decodeJoin(seg: string): JoinPayload | null {
  try {
    const b64 = seg.replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(escape(atob(b64 + "===".slice((b64.length + 3) % 4))));
    const v = JSON.parse(json);
    if (typeof v?.i === "string" && typeof v?.p === "string" && typeof v?.s === "string" && typeof v?.t === "string") return v;
    return null;
  } catch {
    return null;
  }
}
