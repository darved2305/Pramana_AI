/** The signed-in person's own account: memberships, onboarding answers and preferences. */
import { request, requestStream } from "./http";
import type {
  CreateOrganization,
  CurrentAccount,
  OnboardingPatch,
  OnboardingState,
  OrganizationCreated,
  AccountPreferences,
  PreferencesPatch,
  InvitationAccepted,
} from "./types";

/** A fresh idempotency key. Reuse the same key when retrying one action after a lost response. */
export function actionKey(prefix = "web"): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : Math.random().toString(36).slice(2) + Date.now().toString(36);
  return `${prefix}-${random}`.slice(0, 120);
}

export const accountApi = Object.freeze({
  me: (signal?: AbortSignal) => request<CurrentAccount>("core", "/v1/me", { signal }),
  onboarding: async (signal?: AbortSignal) => {
    const res = await requestStream("core", "/v1/onboarding", { signal });
    return { state: (await res.json()) as OnboardingState, etag: res.headers.get("ETag") };
  },
  /** Autosave of the onboarding form; ``etag`` is the version the form was opened at. */
  saveOnboarding: async (patch: OnboardingPatch, etag: string, key: string) => {
    const res = await requestStream("core", "/v1/onboarding", {
      method: "PATCH",
      json: patch,
      headers: { "If-Match": etag, "Idempotency-Key": key },
    });
    return { state: (await res.json()) as OnboardingState, etag: res.headers.get("ETag") };
  },
  /** Remember the last workspace and site, and the home layout, on the server. */
  savePreferences: (patch: PreferencesPatch, key: string) =>
    request<AccountPreferences>("core", "/v1/me/preferences", {
      method: "PATCH",
      json: patch,
      headers: { "Idempotency-Key": key },
    }),
  acceptInvitation: (token: string, key: string) =>
    request<InvitationAccepted>("core", "/v1/invitations/accept", {
      method: "POST",
      json: { token },
      headers: { "Idempotency-Key": key },
    }),
  acceptPendingInvitation: (organizationId: string, invitationId: string, key: string) =>
    request<InvitationAccepted>("core", "/v1/invitations/accept-pending", {
      method: "POST",
      json: { organization_id: organizationId, invitation_id: invitationId },
      headers: { "Idempotency-Key": key },
    }),
  createOrganization: (body: CreateOrganization, key: string) =>
    request<OrganizationCreated>("core", "/v1/orgs", {
      method: "POST",
      json: body,
      headers: { "Idempotency-Key": key },
    }),
});
