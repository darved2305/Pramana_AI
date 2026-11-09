"use client";

/**
 * Consent status for a person, recording or withdrawing it, and permanent erasure.
 * The core enforces who may do each of these; this only decides what to show.
 */
import { useState } from "react";
import { langLabel } from "@/components/app/ParticipantForm";
import { Badge, Button, Dialog, Field, Input, Notice, Select } from "@/components/ui";
import { actionKey } from "@/lib/api/account";
import { ApiError, describeError } from "@/lib/api/http";
import type { OrganizationApi } from "@/lib/api/organization";
import type { ConsentRecord, RecordConsent, SitePerson } from "@/lib/api/types";
import { relative } from "@/lib/data/derive";

type Purpose = RecordConsent["purpose"];
type Channel = RecordConsent["channel"];

export const PURPOSES: { id: Purpose; label: string; meaning: string }[] = [
  { id: "contact_for_investigations", label: "Contact", meaning: "May be contacted and asked questions during investigations" },
  { id: "voice_processing", label: "Voice", meaning: "May have their spoken answers processed" },
];

const CHANNELS: { id: Channel; label: string }[] = [
  { id: "paper", label: "On paper" },
  { id: "web", label: "On a web form" },
  { id: "pstn", label: "On a phone call" },
  { id: "sms", label: "By SMS" },
  { id: "whatsapp", label: "On WhatsApp" },
];

/** What went wrong, in words a site manager can act on. */
export function privacyError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === "NETWORK_UNREACHABLE" || e.code === "UPSTREAM_DOWN") {
      return "Pramana could not be reached. Check your connection and try again.";
    }
    if (e.status === 404) return "This person is no longer listed at this site. Reload the page to see the current list.";
    if (e.status === 403) return "Your account does not have permission to do this. Ask an owner or admin of this workspace.";
    if (e.status >= 500) return "Something went wrong on our side. Please try again.";
  }
  return describeError(e);
}

/** The newest record for a purpose, which may have been withdrawn. */
function latest(records: ConsentRecord[], purpose: Purpose, channel?: Channel): ConsentRecord | undefined {
  return records.find((r) => r.purpose === purpose && (!channel || r.channel === channel));
}

export function ConsentSummary({ records, failed }: { records: ConsentRecord[] | undefined; failed: boolean }) {
  if (failed) return <p className="text-[12px] text-muted">Consent could not be loaded.</p>;
  if (!records) return <p className="text-[12px] text-muted">Checking consent...</p>;
  return (
    <ul className="flex flex-wrap items-center gap-1.5" aria-label="Consent">
      {PURPOSES.map((p) => {
        const r = latest(records, p.id);
        const state = !r
          ? "not recorded"
          : r.decision === "refused"
            ? "refused"
            : r.withdrawn_at
              ? "withdrawn"
              : "given";
        const web = p.id === "contact_for_investigations"
          ? latest(records, p.id, "web")
          : undefined;
        const webAllowed = !!web && web.decision !== "refused" && !web.withdrawn_at;
        return (
          <li key={p.id}>
            <Badge tone={state === "given" ? "ok" : state === "withdrawn" || state === "refused" ? "warn" : "muted"}>
              {p.label}: {state}{r ? ` (${r.channel})` : ""}
            </Badge>
            {p.id === "contact_for_investigations" ? (
              <Badge tone={webAllowed ? "ok" : "muted"}>
                Web questions: {webAllowed ? "allowed" : "not allowed"}
              </Badge>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function ConsentDialog({
  person,
  siteId,
  api,
  records,
  onChanged,
  onClose,
}: {
  person: SitePerson["person"] | null;
  siteId: string;
  api: OrganizationApi;
  records: ConsentRecord[];
  onChanged: () => void;
  onClose: () => void;
}) {
  const [recording, setRecording] = useState<Purpose | null>(null);
  const [notice, setNotice] = useState("1");
  const [language, setLanguage] = useState("");
  const [channel, setChannel] = useState<Channel>("paper");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [requestLink, setRequestLink] = useState<{ path: string; delivery: string } | null>(null);
  const [linkCopied, setLinkCopied] = useState(false);

  const languages = person?.languages.stt_candidates ?? [];
  const chosen = language || languages[0] || "en";

  function close() {
    setRecording(null);
    setLanguage("");
    setError(null);
    setRequestLink(null);
    setLinkCopied(false);
    onClose();
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setRecording(null);
      onChanged();
    } catch (e) {
      setError(privacyError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={!!person}
      onClose={close}
      title={`Consent for ${person?.display_name ?? ""}`}
      description="Record only what this person has actually agreed to."
      footer={<Button onClick={close}>Close</Button>}
    >
      {person ? (
        <div className="flex flex-col gap-3">
          {error ? <Notice tone="bad" title="That did not work">{error}</Notice> : null}
          <ul className="flex flex-col gap-3">
            {PURPOSES.map((p) => {
              const r = latest(records, p.id);
              const active = r && r.decision !== "refused" && !r.withdrawn_at;
              return (
                <li key={p.id} aria-label={p.label} className="flex flex-col gap-2 rounded-[10px] border border-white/[.08] p-3">
                  <p className="text-[14px] font-medium text-fg">{p.meaning}</p>
                  <p className="text-[13px] text-fg-2">
                    {!r
                      ? "Not recorded yet."
                      : r.decision === "refused"
                        ? `Refused ${relative(r.granted_at)}.`
                        : active
                        ? `Given ${relative(r.granted_at)}, notice version ${r.notice_version}, in ${langLabel(r.language)}.`
                        : `Withdrawn ${relative(r.withdrawn_at as string)}.`}
                  </p>
                  {p.id === "contact_for_investigations" ? (
                    <div className="flex flex-col gap-2 rounded-[10px] bg-white/[.025] p-3">
                      <Button
                        size="sm"
                        disabled={busy || requesting}
                        loading={requesting}
                        onClick={async () => {
                          setRequesting(true);
                          setError(null);
                          setRequestLink(null);
                          try {
                            const created = await api.requestConsent(siteId, person.id, { key: actionKey("consent-request") });
                            setRequestLink({ path: created.link_path, delivery: created.email_delivery });
                          } catch (e) {
                            setError(privacyError(e));
                          } finally {
                            setRequesting(false);
                          }
                        }}
                      >
                        Send consent request
                      </Button>
                      {requestLink ? (
                        <>
                          <p className="text-[12px] text-fg-2" aria-live="polite">
                            {requestLink.delivery === "sent"
                              ? "Email sent. You can also copy the link."
                              : requestLink.delivery === "no_email"
                                ? "No email is saved for this person. Copy and share the link."
                                : requestLink.delivery === "failed"
                                  ? "Email could not be confirmed. Copy and share the link."
                                  : "Email is not set up. Copy and share the link."}
                          </p>
                          <div className="flex flex-wrap items-center gap-2">
                            <code className="min-w-0 flex-1 break-all rounded bg-black/20 p-2 text-[11px] text-muted">
                              {typeof window === "undefined" ? requestLink.path : `${window.location.origin}${requestLink.path}`}
                            </code>
                            <Button
                              size="sm"
                              onClick={() => {
                                const link = `${window.location.origin}${requestLink.path}`;
                                void navigator.clipboard?.writeText(link).then(() => setLinkCopied(true));
                              }}
                            >
                              {linkCopied ? "Copied" : "Copy link"}
                            </Button>
                          </div>
                        </>
                      ) : null}
                    </div>
                  ) : null}
                  {recording === p.id ? (
                    <form
                      className="flex flex-col gap-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void run(() =>
                          api.recordConsent(
                            siteId,
                            person.id,
                            { purpose: p.id, notice_version: notice.trim(), language: chosen, channel, evidence: {} },
                            { key: actionKey("consent") },
                          ),
                        );
                      }}
                    >
                      <Field label="Notice version they agreed to">
                        {(f) => <Input {...f} value={notice} maxLength={32} onChange={(e) => setNotice(e.target.value)} />}
                      </Field>
                      <Field label="Language of the notice">
                        {(f) => (
                          <Select {...f} value={chosen} onChange={(e) => setLanguage(e.target.value)}>
                            {[...new Set([...languages, "en"])].map((l) => (
                              <option key={l} value={l}>{langLabel(l)}</option>
                            ))}
                          </Select>
                        )}
                      </Field>
                      <Field label="How they agreed">
                        {(f) => (
                          <Select {...f} value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
                            {CHANNELS.map((c) => (
                              <option key={c.id} value={c.id}>{c.label}</option>
                            ))}
                          </Select>
                        )}
                      </Field>
                      <div className="flex gap-2">
                        <Button type="submit" size="sm" variant="primary" disabled={busy || !notice.trim()}>Save consent</Button>
                        <Button type="button" size="sm" variant="ghost" onClick={() => setRecording(null)}>Cancel</Button>
                      </div>
                    </form>
                  ) : (
                    <div className="flex gap-2">
                      <Button size="sm" disabled={busy} onClick={() => setRecording(p.id)}>
                        {active ? "Record a newer notice" : "Record consent"}
                      </Button>
                      {active ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={busy}
                          aria-label={`Withdraw consent: ${p.label}`}
                          onClick={() => void run(() => api.withdrawConsent(siteId, person.id, p.id, { key: actionKey("withdraw") }))}
                        >
                          Withdraw
                        </Button>
                      ) : null}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </Dialog>
  );
}

export function EraseDialog({
  person,
  siteId,
  api,
  onErased,
  onClose,
}: {
  person: SitePerson["person"] | null;
  siteId: string;
  api: OrganizationApi;
  onErased: (name: string) => void;
  onClose: () => void;
}) {
  const [understood, setUnderstood] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    setUnderstood(false);
    setError(null);
    onClose();
  }

  return (
    <Dialog
      open={!!person}
      onClose={close}
      title={`Permanently erase ${person?.display_name ?? ""}?`}
      description="This cannot be undone. Their name, reports and transcripts are destroyed and nobody can recover them. Past investigations stay, and will show them as Erased person."
      footer={
        <>
          <Button onClick={close}>Cancel</Button>
          <Button
            variant="danger"
            disabled={!understood || busy}
            onClick={async () => {
              if (!person) return;
              setBusy(true);
              setError(null);
              try {
                await api.erasePerson(siteId, person.id, { key: actionKey("erase") });
                const name = person.display_name;
                setUnderstood(false);
                onErased(name);
              } catch (e) {
                setError(privacyError(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Erasing..." : "Erase permanently"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {error ? <Notice tone="bad" title="This person was not erased">{error}</Notice> : null}
        <label className="flex items-start gap-2 text-[14px] text-fg-2">
          <input type="checkbox" className="mt-1" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} />
          I understand this cannot be undone
        </label>
      </div>
    </Dialog>
  );
}
