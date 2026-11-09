/** Saved-site investigation client. Each instance permanently belongs to one organization. */
import { request, requestStream } from "./http";
import type { ListQuery } from "./core";
import type {
  AnswerResult,
  CapabilityGrant,
  CreateSiteInvestigation,
  EventEnvelope,
  InvestigationPage,
  CursorPage,
  InvestigationState,
  ParticipantToken,
  ReplayResult,
  ParticipantSpec,
  SaveDraft,
  SiteModelDocument,
  SiteModelDraft,
  SiteModelSummary,
  ConsentRecord,
  DeleteOrganization,
  ConsentRequestCreated,
  InvestigationForecast,
  MapDriftCheck,
  RecordConsent,
  SitePerson,
  PersonTrackRecord,
  SiteSummary,
  OrganizationSummary,
  ParticipantPatch,
  SitePersonPatch,
  WorkspaceHome,
  WorkspaceMember,
  OrganizationDeletion,
  CreateInvitation,
  InvitationCreated,
  InvitationView,
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
    exportHref: `${root}/export`,
    deleteWorkspace: (body: DeleteOrganization, action: OrganizationAction) =>
      request<OrganizationDeletion>("core", root, {
        method: "DELETE",
        json: body,
        signal: action.signal,
        headers: { "Idempotency-Key": action.key },
      }),
    restoreWorkspace: (action: OrganizationAction) =>
      request<OrganizationSummary>("core", `${root}/restore`, {
        method: "POST",
        signal: action.signal,
        headers: { "Idempotency-Key": action.key },
      }),
    home: (signal?: AbortSignal) => request<WorkspaceHome>("core", `${root}/home`, { signal }),
    members: (query: { limit?: number; cursor?: string } = {}, signal?: AbortSignal) => {
      const params = new URLSearchParams();
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      if (query.cursor) params.set("cursor", query.cursor);
      return request<CursorPage<WorkspaceMember>>("core", `${root}/members${params.size ? `?${params}` : ""}`, { signal });
    },
    invitations: (query: { limit?: number; cursor?: string } = {}, signal?: AbortSignal) => {
      const params = new URLSearchParams();
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      if (query.cursor) params.set("cursor", query.cursor);
      return request<CursorPage<InvitationView>>("core", `${root}/invitations${params.size ? `?${params}` : ""}`, { signal });
    },
    updateMember: (memberId: string, roles: WorkspaceMember["roles"], action: OrganizationAction) =>
      request<WorkspaceMember>("core", `${root}/members/${enc(memberId)}`, {
        method: "PATCH",
        json: { roles },
        signal: action.signal,
        headers: { "Idempotency-Key": action.key },
      }),
    removeMember: (memberId: string, action: OrganizationAction) =>
      mutate<void>(`${root}/members/${enc(memberId)}/remove`, undefined, action),
    invite: (body: CreateInvitation, action: OrganizationAction) =>
      mutate<InvitationCreated>(`${root}/invitations`, body, action),
    revokeInvitation: (id: string, action: OrganizationAction) =>
      mutate<void>(`${root}/invitations/${enc(id)}/revoke`, undefined, action),
    sites: (query: { limit?: number; cursor?: string } = {}, signal?: AbortSignal) => {
      const params = new URLSearchParams();
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      if (query.cursor) params.set("cursor", query.cursor);
      return request<CursorPage<SiteSummary>>("core", `${root}/sites${params.size ? `?${params}` : ""}`, { signal });
    },
    trackRecord: (siteId: string, personIds: string[] = [], signal?: AbortSignal) => {
      const params = new URLSearchParams();
      params.set("limit", "100");
      personIds.forEach((id) => params.append("person_id", id));
      return request<CursorPage<PersonTrackRecord>>("core", `${site(siteId)}/people/track-record?${params}`, { signal });
    },
    people: (siteId: string, query: { limit?: number; cursor?: string; q?: string } = {}, signal?: AbortSignal) => {
      const params = new URLSearchParams();
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      if (query.cursor) params.set("cursor", query.cursor);
      if (query.q?.trim()) params.set("q", query.q.trim());
      return request<CursorPage<SitePerson>>("core", `${site(siteId)}/people${params.size ? `?${params}` : ""}`, { signal });
    },
    addPerson: (siteId: string, person: ParticipantSpec, action: OrganizationAction) =>
      mutate<SitePerson>(`${site(siteId)}/people`, person, action),
    updatePerson: (
      siteId: string, personId: string, patch: SitePersonPatch, version: number, action: OrganizationAction,
    ) =>
      request<SitePerson>("core", `${site(siteId)}/people/${enc(personId)}`, {
        method: "PATCH",
        json: patch,
        signal: action.signal,
        headers: { "Idempotency-Key": action.key, "If-Match": `"${version}"` },
      }),
    removePerson: (siteId: string, personId: string, action: OrganizationAction) =>
      mutate<void>(`${site(siteId)}/people/${enc(personId)}/remove`, undefined, action),
    erasePerson: (siteId: string, personId: string, action: OrganizationAction) =>
      mutate<void>(`${site(siteId)}/people/${enc(personId)}/erase`, undefined, action),
    consents: (
      siteId: string,
      personId: string,
      query: { limit?: number; cursor?: string; purpose?: ConsentRecord["purpose"] } = {},
      signal?: AbortSignal,
    ) => {
      const params = new URLSearchParams();
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      if (query.cursor) params.set("cursor", query.cursor);
      if (query.purpose) params.set("purpose", query.purpose);
      return request<CursorPage<ConsentRecord>>(
        "core",
        `${site(siteId)}/people/${enc(personId)}/consents${params.size ? `?${params}` : ""}`,
        { signal },
      );
    },
    recordConsent: (siteId: string, personId: string, body: RecordConsent, action: OrganizationAction) =>
      mutate<ConsentRecord>(`${site(siteId)}/people/${enc(personId)}/consents`, body, action),
    withdrawConsent: (siteId: string, personId: string, purpose: RecordConsent["purpose"], action: OrganizationAction) =>
      mutate<void>(`${site(siteId)}/people/${enc(personId)}/consents/${enc(purpose)}/withdraw`, undefined, action),
    requestConsent: (siteId: string, personId: string, action: OrganizationAction) =>
      mutate<ConsentRequestCreated>(`${site(siteId)}/people/${enc(personId)}/consent-requests`, undefined, action),
    site: (id: string, signal?: AbortSignal) => request<SiteSummary>("core", site(id), { signal }),
    models: (id: string, query: { limit?: number; cursor?: string } = {}, signal?: AbortSignal) => {
      const params = new URLSearchParams();
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      if (query.cursor) params.set("cursor", query.cursor);
      return request<CursorPage<SiteModelSummary>>("core", `${site(id)}/models${params.size ? `?${params}` : ""}`, { signal });
    },
    model: (siteId: string, modelId: string, signal?: AbortSignal) =>
      request<SiteModelDocument>("core", `${site(siteId)}/models/${enc(modelId)}`, { signal }),
    listInvestigations: (query: ListQuery = {}, signal?: AbortSignal) => {
      const params = new URLSearchParams();
      query.status?.forEach((status) => params.append("status", status));
      if (query.q?.trim()) params.set("q", query.q.trim());
      if (query.limit !== undefined) params.set("limit", String(query.limit));
      if (query.cursor) params.set("cursor", query.cursor);
      const suffix = params.size ? `?${params}` : "";
      return request<InvestigationPage>("core", investigations + suffix, { signal });
    },
    createInvestigation: (body: CreateSiteInvestigation, action: OrganizationAction) =>
      mutate<InvestigationState>(investigations, body, action),
    getInvestigation: (id: string, signal?: AbortSignal, token?: string) =>
      request<InvestigationState>("core", investigation(id), { signal, token }),
    mapDrift: (id: string, signal?: AbortSignal) =>
      request<MapDriftCheck>("core", `${investigation(id)}/map-drift`, { signal }),
    forecast: (id: string, signal?: AbortSignal) =>
      request<InvestigationForecast>("core", `${investigation(id)}/forecast`, { signal }),
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
    recheckAvailability: (id: string, action: OrganizationAction) =>
      mutate<InvestigationState>(`${investigation(id)}/availability/recheck`, undefined, action),
    overrideQuietHours: (id: string, reason: string, action: OrganizationAction) =>
      mutate<InvestigationState>(`${investigation(id)}/quiet-hours/override`, { reason }, action),
  });
}

export type OrganizationApi = ReturnType<typeof organizationApi>;
