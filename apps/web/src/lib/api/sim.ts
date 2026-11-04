/**
 * Simulator client, used only from the participant page with that participant's own
 * token (API guide, section 2). The core returns an absolute `sim_url`; the browser
 * always goes through the same-origin /api/sim proxy instead.
 */
import { request } from "./http";
import type { ParticipantView } from "./types";

const enc = encodeURIComponent;

export const sim = {
  view: (scenarioId: string, token: string, signal?: AbortSignal) =>
    request<ParticipantView>("sim", `/sim/v1/scenarios/${enc(scenarioId)}/view`, { token, signal }),

  move: (scenarioId: string, token: string, to: string) =>
    request<unknown>("sim", `/sim/v1/scenarios/${enc(scenarioId)}/move`, { method: "POST", token, json: { to } }),

  act: (scenarioId: string, token: string, body: { action: string; target: string; capability: string }) =>
    request<unknown>("sim", `/sim/v1/scenarios/${enc(scenarioId)}/act`, { method: "POST", token, json: body }),
};
