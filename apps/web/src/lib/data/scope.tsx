"use client";

/**
 * Where the investigation screens send their requests and links. The same screens serve the
 * single-site console (``/app/investigations``) and every workspace
 * (``/app/<workspace>/investigations``); only this scope differs. Inside a workspace every
 * call goes to ``/v1/orgs/<workspace>/...`` and every write carries an idempotency key.
 */
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { actionKey } from "@/lib/api/account";
import { core, type ListQuery } from "@/lib/api/core";
import type { OrganizationApi } from "@/lib/api/organization";
import type {
  AnswerResult,
  EventEnvelope,
  InvestigationPage,
  InvestigationState,
  ParticipantToken,
  ReplayResult,
  SitePack,
  SubmitAnswer,
} from "@/lib/api/types";
import { packFromSpec } from "@/lib/builder/sitePack";

export interface InvestigationScope {
  /** Page path prefix for investigation links: ``/app`` or ``/app/<workspace>``. */
  base: string;
  /** API path prefix (after ``/api/core``): ``/v1`` or ``/v1/orgs/<workspace>``. */
  apiRoot: string;
  workspace: string | null;
  listInvestigations(q: ListQuery, signal?: AbortSignal): Promise<InvestigationPage>;
  getInvestigation(id: string, signal?: AbortSignal): Promise<InvestigationState>;
  events(id: string, afterSeq: number, signal?: AbortSignal, token?: string): Promise<EventEnvelope[]>;
  replayCheck(id: string, signal?: AbortSignal): Promise<ReplayResult>;
  answer(id: string, body: SubmitAnswer): Promise<AnswerResult>;
  requestApproval(id: string, body: { action: string; target: string; participant_id: string }): Promise<InvestigationState>;
  decideApproval(id: string, approvalId: string, body: { decision: "approve" | "deny"; note?: string }): Promise<InvestigationState>;
  reveal(id: string): Promise<InvestigationState>;
  participantToken(id: string, participantId: string): Promise<ParticipantToken>;
  /** The site map an investigation ran on: its pinned model version inside a workspace. */
  sitePack(state: InvestigationState, signal?: AbortSignal): Promise<SitePack>;
}

const legacyScope: InvestigationScope = {
  base: "/app",
  apiRoot: "/v1",
  workspace: null,
  listInvestigations: (q, signal) => core.listInvestigations(q, signal),
  getInvestigation: (id, signal) => core.getInvestigation(id, signal),
  events: (id, after, signal, token) => core.events(id, after, signal, token),
  replayCheck: (id, signal) => core.replayCheck(id, signal),
  answer: (id, body) => core.answer(id, body),
  requestApproval: (id, body) => core.requestApproval(id, body),
  decideApproval: (id, approvalId, body) => core.decideApproval(id, approvalId, body),
  reveal: (id) => core.reveal(id),
  participantToken: (id, pid) => core.participantToken(id, pid),
  sitePack: (state, signal) => core.pack(state.pack_id, signal),
};

export function workspaceScope(api: OrganizationApi): InvestigationScope {
  const key = (what: string) => ({ key: actionKey(what) });
  return {
    base: `/app/${api.org}`,
    apiRoot: `/v1/orgs/${encodeURIComponent(api.org)}`,
    workspace: api.org,
    listInvestigations: (q, signal) => api.listInvestigations(q, signal),
    getInvestigation: (id, signal) => api.getInvestigation(id, signal),
    events: (id, after, signal) => api.events(id, after, signal),
    replayCheck: (id, signal) => api.replayCheck(id, signal),
    answer: (id, body) => api.answer(id, body, key("answer")),
    requestApproval: (id, body) => api.requestApproval(id, body, key("approval")),
    decideApproval: (id, approvalId, body) => api.decideApproval(id, approvalId, body, key("decision")),
    reveal: (id) => api.reveal(id, key("reveal")),
    participantToken: (id, pid) => api.participantToken(id, pid, key("link")),
    sitePack: async (state, signal) => {
      if (!state.site_id || !state.site_model_id) throw new Error("This investigation has no saved site model.");
      return packFromSpec((await api.model(state.site_id, state.site_model_id, signal)).spec);
    },
  };
}

const ScopeContext = createContext<InvestigationScope>(legacyScope);

export function InvestigationScopeProvider({ api, children }: { api: OrganizationApi; children: ReactNode }) {
  const value = useMemo(() => workspaceScope(api), [api]);
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

export function useInvestigationScope(): InvestigationScope {
  return useContext(ScopeContext);
}
