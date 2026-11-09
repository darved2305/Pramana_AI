import { request } from "./http";
import type { ConsentLinkView, ConsentResponseView } from "./types";

const path = (code: string) => `/v1/consent-links/${encodeURIComponent(code)}`;

export const consentApi = {
  read: (code: string, signal?: AbortSignal) =>
    request<ConsentLinkView>("core", path(code), { signal }),
  respond: (code: string, decision: "granted" | "refused") =>
    request<ConsentResponseView>("core", path(code), {
      method: "POST",
      json: { decision },
    }),
};
