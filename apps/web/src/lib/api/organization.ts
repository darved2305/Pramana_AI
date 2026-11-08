/** Saved-site investigation client. Each instance permanently belongs to one organization. */
import { request, requestStream } from "./http";
import type { ListQuery } from "./core";
import type {
  AnswerResult,
  CapabilityGrant,
  CreateSiteInvestigation,
  EventEnvelope,
  InvestigationPage,
  InvestigationState,
  ParticipantToken,
  ReplayResult,
  ParticipantSpec,
  SaveDraft,
  SiteModelDocument,
  SiteModelDraft,
  SiteModelSummary,
  SitePerson,
  SiteSummary,
  ParticipantPatch,
  WorkspaceHome,
  SubmitAnswer,
} from "./types";

/** Keep the same key and payload when retrying one action after a lost response. */
export interface OrganizationAction {
  key: string;
  token?: string;
  signal?: AbortSignal;
}

const enc = encodeURIComponent;

export function organizationApi(org: string) {
  if (!/^(?:[a-z0-9][a-z0-9-]{1,38}[a-z0-9]|org_[0-9A-HJKMNP-TV-Z]{26})$/i.test(org)) {
    throw new TypeError("Choose a valid organization before loading its data.");
  }
  const root = `/v1/orgs/${enc(org)}`;
  const investigations = `${root}/investigations`;
  const investigation = (id: string) => `${investigations}/${enc(id)}`;
  const site = (id: string) => `${root}/sites/${enc(id)}`;
  const mutate = <T>(path: string, json: unknown, action: OrganizationAction) =>
    request<T>("core", path, {
      method: "POST",
      json,
      token: action.token,
      signal: action.signal,
      headers: { "Idempotency-Key": action.key },
    });

  // No mutable selected-org singleton: concurrent server renders and two tabs may use
  // different instances without redirecting one person's requests into another workspace.
  return Object.freeze({
    org,
    home: (signal?: AbortSignal) => request<WorkspaceHome>("core", `${root}/home`, { signal }),
    sites: (signal?: AbortSignal) => request<SiteSummary[]>("core", `${root}/sites`, { signal }),
    people: (siteId: string, signal?: AbortSignal) =>
      request<SitePerson[]>("core", `${site(siteId)}/people`, { signal }),
    addPerson: (siteId: string, person: ParticipantSpec, action: OrganizationAction) =>
      mutate<SitePerson>(`${site(siteId)}/people`, person, action),
    updatePerson: (
      siteId: string, personId: string, patch: ParticipantPatch, version: number, action: OrganizationAction,
    ) =>
      request<SitePerson>("core", `${site(siteId)}/people/${enc(personId)}`, {
        method: "PATCH",
        json: patch,
        signal: action.signal,
        headers: { "Idempotency-Key": action.key, "If-Match": `"${version}"` },
      }),
    removePerson: (siteId: string, personId: string, action: OrganizationAction) =>
      mutate<void>(`${site(siteId)}/people/${enc(personId)}/remove`, undefined, action),
    site: (id: string, signal?: AbortSignal) => request<SiteSummary>("core", site(id), { signal }),
    models: (id: string, signal?: AbortSignal) =>
      request<SiteModelSummary[]>("core", `${site(id)}/models`, { signal }),
    model: (siteId: string, modelId: string, signal?: AbortSignal) =>
      request<SiteModelDocument>("core", `${site(siteId)}/models/${enc(modelId)}`, { signal }),
    listInvestigations: (query: ListQuery = {}, signal?: AbortSignal) => {
      const params = new URLSearchParams();
      query.status?.forEach((status) => params.append("status", status));
      if (query.q?.trim()) params.set("q", query.q.trim());
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      if (query.offset !== undefined) params.set("offset", String(query.offset));
      const suffix = params.size ? `?${params}` : "";
      return request<InvestigationPage>("core", investigations + suffix, { signal });
    },
    createInvestigation: (body: CreateSiteInvestigation, action: OrganizationAction) =>
      mutate<InvestigationState>(investigations, body, action),
    getInvestigation: (id: string, signal?: AbortSignal, token?: string) =>
      request<InvestigationState>("core", investigation(id), { signal, token }),
    replayCheck: (id: string, signal?: AbortSignal) =>
      request<ReplayResult>("core", `${investigation(id)}/replay`, { signal }),
    events: (id: string, afterSeq: number, signal?: AbortSignal) =>
      request<EventEnvelope[]>("core", `${investigation(id)}/events?after_seq=${afterSeq}`, { signal }),
    answer: (id: string, body: SubmitAnswer, action: OrganizationAction) =>
      mutate<AnswerResult>(`${investigation(id)}/answers`, body, action),
    reveal: (id: string, action: OrganizationAction) =>
      mutate<InvestigationState>(`${investigation(id)}/reveal`, undefined, action),
    requestApproval: (
      id: string,
      body: { action: string; target: string; participant_id: string },
      action: OrganizationAction,
    ) => mutate<InvestigationState>(`${investigation(id)}/approvals`, body, action),
    decideApproval: (
      id: string, approvalId: string, body: { decision: "approve" | "deny"; note?: string },
      action: OrganizationAction,
    ) => mutate<InvestigationState>(`${investigation(id)}/approvals/${enc(approvalId)}/decision`, body, action),
    capability: (id: string, approvalId: string, participantId: string, action: OrganizationAction) =>
      mutate<CapabilityGrant>(
        `${investigation(id)}/approvals/${enc(approvalId)}/capability?participant_id=${enc(participantId)}`,
        undefined, action,
      ),
    reportIntervention: (
      id: string, body: { approval_id: string; participant_id: string }, action: OrganizationAction,
    ) => mutate<InvestigationState>(`${investigation(id)}/interventions`, body, action),
    /** The site's open draft, with the version to send back when saving it. */
    getDraft: async (siteId: string, signal?: AbortSignal) => {
      const res = await requestStream("core", `${site(siteId)}/draft`, { signal });
      return { draft: (await res.json()) as SiteModelDraft, etag: res.headers.get("ETag") };
    },
    saveDraft: async (siteId: string, body: SaveDraft, etag: string | null, action: OrganizationAction) => {
      const headers: Record<string, string> = { "Idempotency-Key": action.key };
      if (etag) headers["If-Match"] = etag;
      const res = await requestStream("core", `${site(siteId)}/draft`, {
        method: "POST",
        json: body,
        headers,
        signal: action.signal,
      });
      return { draft: (await res.json()) as SiteModelDraft, etag: res.headers.get("ETag") };
    },
    checkDraft: (siteId: string, draftId: string, people: ParticipantSpec[] | null, action: OrganizationAction) =>
      mutate<SiteModelDraft>(`${site(siteId)}/draft/${enc(draftId)}/health`, people ?? undefined, action),
    publishDraft: (siteId: string, draftId: string, action: OrganizationAction) =>
      mutate<SiteModelSummary>(`${site(siteId)}/draft/${enc(draftId)}/publish`, undefined, action),
    discardDraft: (siteId: string, draftId: string, action: OrganizationAction) =>
      mutate<void>(`${site(siteId)}/draft/${enc(draftId)}/discard`, undefined, action),
    participantToken: (id: string, participantId: string, action: OrganizationAction) =>
      mutate<ParticipantToken & { org_id: string }>(
        `${investigation(id)}/participants/${enc(participantId)}/token`, undefined, action,
      ),
  });
}

export type OrganizationApi = ReturnType<typeof organizationApi>;
