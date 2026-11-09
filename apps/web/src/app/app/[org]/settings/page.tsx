"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Avatar } from "@/components/app/Avatar";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, KeyValue, Notice, PageHeader, Skeleton } from "@/components/ui";
import { IconCopy } from "@/components/ui/icons";
import { actionKey } from "@/lib/api/account";
import { ApiError, describeError } from "@/lib/api/http";
import type {
  CreateDomain,
  CreateInvitation,
  InvitationCreated,
  JoinRequestDecision,
  JoinRequestView,
  OrganizationDomain,
  WorkspaceMember,
} from "@/lib/api/types";
import { refreshAccount } from "@/lib/data/account";
import { joinRequestLabel, relative } from "@/lib/data/derive";
import { useCursorList, useLoad } from "@/lib/data/hooks";
import { useWorkspace } from "@/lib/org/context";

type InvitedRole = CreateInvitation["roles"][number];

const ROLE_HELP: { id: InvitedRole | "owner"; label: string; can: string }[] = [
  { id: "owner", label: "Owner", can: "Everything an admin can do. Created the workspace." },
  { id: "admin", label: "Admin", can: "Invites people, describes sites, runs investigations. Does not approve repairs." },
  { id: "operator", label: "Operator", can: "Describes sites, adds people, runs investigations and proposes repairs." },
  { id: "approver", label: "Approver", can: "Approves or denies repairs proposed by someone else." },
  { id: "viewer", label: "Viewer", can: "Sees everything, changes nothing." },
];

export default function WorkspaceSettingsPage() {
  const ws = useWorkspace();
  const router = useRouter();
  const canManage = ws.roles.has("owner") || ws.roles.has("admin");
  const members = useCursorList(`members|${ws.org.id}`, (cursor, s) => ws.api.members({ limit: 25, cursor }, s));
  const invitations = useCursorList(canManage ? `invitations|${ws.org.id}` : null, (cursor, s) => ws.api.invitations({ limit: 25, cursor }, s));
  const [email, setEmail] = useState("");
  const [roles, setRoles] = useState<InvitedRole[]>(["operator"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<{ id: string; email: string; url: string; delivery: InvitationCreated["email_delivery"] } | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [exportAcknowledged, setExportAcknowledged] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deletionError, setDeletionError] = useState<string | null>(null);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !roles.length) return;
    setBusy(true);
    setError(null);
    try {
      const created = await ws.api.invite({ email: email.trim(), roles }, { key: actionKey("invite") });
      setLink({
        id: created.invitation.id,
        email: created.invitation.email,
        url: `${window.location.origin}${created.accept_path}`,
        delivery: created.email_delivery,
      });
      setCopied(false);
      setEmail("");
      invitations.reload();
    } catch (x) {
      setError(describeError(x));
    } finally {
      setBusy(false);
    }
  }

  async function deleteWorkspace() {
    if (confirmation !== ws.org.name || !exportAcknowledged) return;
    setDeleting(true);
    setDeletionError(null);
    try {
      await ws.api.deleteWorkspace(
        { confirmation },
        { key: actionKey("delete-workspace") },
      );
      await refreshAccount();
      router.replace("/app");
      router.refresh();
    } catch (x) {
      setDeletionError(describeError(x));
      setDeleting(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 pt-4">
      <PageHeader title="Workspace settings" subtitle="Who is in this workspace, what each role may do, and inviting your team." />

      <Card className="flex flex-col gap-3 p-5">
        <CardHeader title={ws.org.name} subtitle="Workspace details" />
        <dl className="grid gap-3 sm:grid-cols-2">
          <KeyValue k="Address" v={<span className="font-mono text-[13px]">/app/{ws.org.slug}</span>} />
          <KeyValue k="Kind" v={ws.org.kind} />
          <KeyValue k="Time zone" v={ws.org.timezone} />
          <KeyValue k="Your roles" v={ws.org.roles.join(", ")} />
        </dl>
      </Card>

      {ws.roles.has("owner") ? (
        <Card className="flex flex-col gap-4 border-bad/30 p-5">
          <CardHeader title="Delete workspace" subtitle="Pause access now, then permanently erase personal data after 30 days." />
          <p className="text-[14px] text-fg-2">
            Download an archive first. It contains site models, members, consent records, investigation reports, and participant names. Treat it as personal data and store it securely. The owner can restore this workspace during the 30-day window.
          </p>
          <div>
            <a
              href={`/api/core${ws.api.exportHref}`}
              className="text-[14px] text-accent underline underline-offset-4"
            >
              Download workspace export
            </a>
          </div>
          <label className="flex items-start gap-3 text-[13px] text-fg-2">
            <input
              type="checkbox"
              className="mt-1"
              checked={exportAcknowledged}
              onChange={(event) => setExportAcknowledged(event.target.checked)}
            />
            <span>I downloaded the export or have decided I do not need a copy.</span>
          </label>
          <Field label={`Type ${ws.org.name} to confirm`}>
            {(a) => (
              <Input
                {...a}
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                autoComplete="off"
              />
            )}
          </Field>
          {deletionError ? <p role="alert" className="text-[13px] text-bad">{deletionError}</p> : null}
          <div>
            <Button
              variant="danger"
              disabled={deleting || !exportAcknowledged || confirmation !== ws.org.name}
              onClick={() => void deleteWorkspace()}
            >
              {deleting ? "Deleting workspace..." : "Delete workspace"}
            </Button>
          </div>
        </Card>
      ) : null}

      <Card className="flex flex-col gap-4 p-5">
        <CardHeader title="Members" subtitle="People with an account here. The people asked during investigations are listed per site under People." />
        {members.status === "loading" ? <Skeleton className="h-24" /> : null}
        {members.status === "error" ? <ErrorState error={members.error} onRetry={members.reload} /> : null}
        {members.status === "ready" ? (
          <ul className="flex flex-col divide-y divide-white/[.06]" aria-label="Members">
            {members.data.items.map((m) => (
              <MemberRow
                key={m.id}
                member={m}
                canManage={canManage}
                isOwner={ws.roles.has("owner")}
                onChanged={members.reload}
                onLeft={async () => {
                  await refreshAccount();
                  router.push("/app");
                }}
              />
            ))}
          </ul>
        ) : null}
        {members.status === "ready" && members.data.next_cursor ? (
          <div className="flex justify-center"><Button size="sm" onClick={members.loadMore} disabled={members.loadingMore}>{members.loadingMore ? "Loading..." : "Load more members"}</Button></div>
        ) : null}
        {members.moreError ? <p role="alert" className="text-[13px] text-bad">Could not load more members. <button className="underline" onClick={members.loadMore}>Try again</button></p> : null}
      </Card>

      {canManage ? <JoinRequestsPanel /> : null}

      {canManage ? (
        <Card className="flex flex-col gap-4 p-5">
          <CardHeader
            title="Invite someone"
            subtitle="You get a link to send them on WhatsApp, email or chat. It works for 7 days, only for the address you enter, and only once."
          />
          <form onSubmit={invite} className="flex flex-col gap-4">
            <Field label="Their email address" hint="They sign in with this address (Google or password) to accept.">
              {(a) => <Input {...a} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" />}
            </Field>
            <fieldset>
              <legend className="mb-2 text-[13px] font-medium text-fg-2">Roles</legend>
              <div className="flex flex-col gap-2">
                {ROLE_HELP.filter((r) => r.id !== "owner").map((r) => {
                  const id = r.id as InvitedRole;
                  const on = roles.includes(id);
                  return (
                    <label key={r.id} className="flex cursor-pointer items-start gap-3 rounded-[12px] p-3 shadow-[inset_0_0_0_0.8px_var(--app-line)]">
                      <input type="checkbox" className="mt-1" checked={on} onChange={() => setRoles(on ? roles.filter((x) => x !== id) : [...roles, id])} />
                      <span>
                        <span className="block text-[14px] text-fg">{r.label}</span>
                        <span className="block text-[12px] text-muted">{r.can}</span>
                      </span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
            {error ? <p role="alert" className="text-[13px] text-bad">{error}</p> : null}
            <div>
              <Button type="submit" variant="primary" disabled={busy || !email.trim() || !roles.length}>
                {busy ? "Creating link..." : "Create invitation link"}
              </Button>
            </div>
          </form>
          {link ? (
            <Notice tone="ok" title={`Invitation link for ${link.email}`}>
              {link.delivery === "sent" ? (
                <p>We emailed this link to {link.email}. You can also copy it now: for safety it is not shown again.</p>
              ) : link.delivery === "failed" ? (
                <p>We could not confirm the email was sent, so please send this link yourself. Copy it now: for safety it is not shown again.</p>
              ) : (
                <p>Copy it now and send it to them: for safety it is not shown again. Creating a new one replaces it.</p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <code className="max-w-full break-all rounded-[8px] bg-white/[.05] px-2 py-1 font-mono text-[12px]">{link.url}</code>
                <Button
                  size="sm"
                  onClick={async () => {
                    await navigator.clipboard.writeText(link.url);
                    setCopied(true);
                  }}
                >
                  <IconCopy /> {copied ? "Copied" : "Copy link"}
                </Button>
              </div>
            </Notice>
          ) : null}
          {invitations.status === "error" ? <ErrorState error={invitations.error} onRetry={invitations.reload} /> : null}
          {invitations.status === "ready" && invitations.data.items.length ? (
            <ul className="flex flex-col divide-y divide-white/[.06]" aria-label="Invitations">
              {invitations.data.items.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center gap-3 py-2.5 text-[14px]">
                  <span className="min-w-0 flex-1 truncate text-fg">{i.email}</span>
                  <span className="text-[12px] text-muted">{i.roles.join(", ")} · {relative(i.created_at)}</span>
                  <Badge tone={i.status === "pending" ? "warn" : i.status === "accepted" ? "ok" : "muted"}>{i.status}</Badge>
                  {i.status === "pending" ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        try {
                          await ws.api.revokeInvitation(i.id, { key: actionKey("revoke") });
                          setLink((current) => current?.id === i.id ? null : current);
                          invitations.reload();
                        } catch (x) {
                          setError(describeError(x));
                        }
                      }}
                    >
                      Withdraw
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {invitations.status === "ready" && invitations.data.next_cursor ? (
            <div className="flex justify-center"><Button size="sm" onClick={invitations.loadMore} disabled={invitations.loadingMore}>{invitations.loadingMore ? "Loading..." : "Load more invitations"}</Button></div>
          ) : null}
          {invitations.moreError ? <p role="alert" className="text-[13px] text-bad">Could not load more invitations. <button className="underline" onClick={invitations.loadMore}>Try again</button></p> : null}
        </Card>
      ) : null}

      {canManage ? <DomainClaimsPanel /> : null}

      <Card className="flex flex-col gap-3 p-5">
        <CardHeader title="What each role may do" subtitle="Separation of duties: the person who proposes a repair can never approve it." />
        <ul className="flex flex-col gap-2 text-[14px]">
          {ROLE_HELP.map((r) => (
            <li key={r.id} className="flex flex-wrap gap-2">
              <Badge>{r.label}</Badge>
              <span className="text-fg-2">{r.can}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

type JoinPolicy = NonNullable<CreateDomain["join_policy"]>;

const POLICY_LABEL: Record<JoinPolicy, string> = {
  request: "Ask an admin first",
  auto: "Join automatically as viewer",
  off: "Off",
};

/**
 * One idempotency key per action, reused when the same action is retried after a lost
 * response, and dropped once the server has given a definite answer.
 */
function useActionKeys() {
  const keys = useRef(new Map<string, string>());
  return {
    get(action: string) {
      const key = keys.current.get(action) ?? actionKey(action.split(":")[0]);
      keys.current.set(action, key);
      return key;
    },
    settle(action: string, error?: unknown) {
      const retryable =
        error !== undefined &&
        (!(error instanceof ApiError) || error.unreachable || error.code === "IDEMPOTENCY_IN_FLIGHT");
      if (!retryable) keys.current.delete(action);
    },
  };
}

/** Requests from people at a verified domain. Shown once anyone has asked. */
function JoinRequestsPanel() {
  const ws = useWorkspace();
  const requests = useCursorList(
    `join-requests|${ws.org.id}`,
    (cursor, signal) => ws.api.joinRequests({ limit: 25, cursor }, signal),
  );
  const keys = useActionKeys();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(item: JoinRequestView, role?: JoinRequestDecision["role"]) {
    const action = role ? `join-approve:${item.id}:${role}` : `join-decline:${item.id}`;
    setBusyId(item.id);
    setError(null);
    try {
      if (role) await ws.api.approveJoinRequest(item.id, { role }, { key: keys.get(action) });
      else await ws.api.declineJoinRequest(item.id, { key: keys.get(action) });
      keys.settle(action);
      requests.reload();
    } catch (e) {
      keys.settle(action, e);
      setError(describeError(e));
      if (e instanceof ApiError && e.status === 404) requests.reload();
    } finally {
      setBusyId(null);
    }
  }

  if (requests.status === "error") {
    return (
      <Card id="join-requests" className="flex flex-col gap-4 p-5">
        <CardHeader title="Requests to join" subtitle="We could not load requests to join this workspace." />
        <ErrorState error={requests.error} onRetry={requests.reload} />
      </Card>
    );
  }
  if (requests.status !== "ready" || requests.data.items.length === 0) return null;
  return (
    <Card id="join-requests" className="flex flex-col gap-4 p-5">
      <CardHeader
        title="Requests to join"
        subtitle="Pending requests appear first, followed by recent decisions. Each person used Google with an address at your verified domain."
      />
      {error ? <p role="alert" className="text-[13px] text-bad">{error}</p> : null}
      <ul className="flex flex-col divide-y divide-white/[.06]" aria-label="Workspace join requests">
        {requests.data.items.map((item) => (
          <JoinRequestRow key={item.id} item={item} busy={busyId === item.id} disabled={busyId !== null} onDecide={decide} />
        ))}
      </ul>
      {requests.data.next_cursor ? (
        <div className="flex justify-center">
          <Button size="sm" onClick={requests.loadMore} disabled={requests.loadingMore}>
            {requests.loadingMore ? "Loading..." : "Load more requests"}
          </Button>
        </div>
      ) : null}
      {requests.moreError ? <p role="alert" className="text-[13px] text-bad">Could not load more requests. <button className="underline" onClick={requests.loadMore}>Try again</button></p> : null}
    </Card>
  );
}

function JoinRequestRow({
  item,
  busy,
  disabled,
  onDecide,
}: {
  item: JoinRequestView;
  busy: boolean;
  disabled: boolean;
  onDecide: (item: JoinRequestView, role?: JoinRequestDecision["role"]) => void;
}) {
  const [role, setRole] = useState<JoinRequestDecision["role"]>("viewer");
  const { label, tone } = joinRequestLabel(item);
  const when = item.status === "pending" ? `Asked ${relative(item.requested_at)}` : relative(item.decided_at ?? item.requested_at);
  const roleName = item.role ? `${item.role[0].toUpperCase()}${item.role.slice(1)}` : null;
  return (
    <li className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <p className="break-words text-[14px] text-fg">
          {item.requester_name} <span className="text-muted">{item.requester_email}</span>
        </p>
        <p className="mt-1 text-[12px] text-muted">{item.status === "approved" && roleName ? `${when} · ${roleName}` : when}</p>
      </div>
      {item.status === "pending" ? (
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor={`join-role-${item.id}`}>Role for {item.requester_name}</label>
          <select
            id={`join-role-${item.id}`}
            value={role}
            onChange={(e) => setRole(e.target.value as JoinRequestDecision["role"])}
            disabled={disabled}
            className="min-h-10 rounded-[10px] border border-white/20 bg-ink px-3 text-[13px] text-fg"
          >
            <option value="viewer">Viewer</option>
            <option value="operator">Operator</option>
            <option value="approver">Approver</option>
            <option value="admin">Admin</option>
          </select>
          <Button size="sm" variant="primary" disabled={disabled} onClick={() => onDecide(item, role)}>
            {busy ? "Saving..." : "Approve"}
          </Button>
          <Button size="sm" variant="ghost" disabled={disabled} onClick={() => onDecide(item)}>
            Decline
          </Button>
        </div>
      ) : (
        <Badge tone={tone}>{label}</Badge>
      )}
    </li>
  );
}

/** Domains this workspace has claimed, how each was proven, and who may join from it. */
function DomainClaimsPanel() {
  const ws = useWorkspace();
  const domains = useLoad(`domains|${ws.org.id}`, (signal) => ws.api.domains(signal));
  const keys = useActionKeys();
  const [domain, setDomain] = useState("");
  const [verification, setVerification] = useState<CreateDomain["verification"]>("google_hd");
  const [policy, setPolicy] = useState<JoinPolicy>("request");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(busy: string, action: string, call: (key: string) => Promise<unknown>) {
    setBusyId(busy);
    setError(null);
    try {
      await call(keys.get(action));
      keys.settle(action);
      domains.reload();
      return true;
    } catch (x) {
      keys.settle(action, x);
      setError(describeError(x));
      return false;
    } finally {
      setBusyId(null);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const value = domain.trim();
    if (!value) return;
    const ok = await run("add", `domain-add:${value}:${verification}:${policy}`, (key) =>
      ws.api.addDomain({ domain: value, verification, join_policy: policy }, { key }),
    );
    if (ok) setDomain("");
  }

  function remove(item: OrganizationDomain) {
    if (!window.confirm(`Remove ${item.domain}? People at this domain will no longer see this workspace, and requests still waiting will be closed.`)) return;
    void run(item.domain, `domain-remove:${item.domain}`, (key) => ws.api.removeDomain(item.domain, { key }));
  }

  return (
    <Card className="flex flex-col gap-4 p-5">
      <CardHeader
        title="Join by email domain"
        subtitle="Let colleagues who sign in with Google at your organization's domain find this workspace. First prove the domain is yours."
      />
      {error ? <p role="alert" className="text-[13px] text-bad">{error}</p> : null}
      <form onSubmit={add} className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Field label="Email domain" hint="The part after @, for example college.edu">
          {(a) => (
            <Input
              {...a}
              type="text"
              inputMode="url"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="college.edu"
            />
          )}
        </Field>
        <label className="flex flex-col gap-1.5 text-[13px] text-fg-2">
          How to prove it is yours
          <select value={verification} onChange={(e) => setVerification(e.target.value as CreateDomain["verification"])} className="min-h-[44px] rounded-[10px] border border-white/20 bg-ink px-3 text-fg">
            <option value="google_hd">My Google Workspace sign-in</option>
            <option value="dns_txt">A DNS TXT record</option>
          </select>
        </label>
        <label className="flex flex-col gap-1.5 text-[13px] text-fg-2">
          Who can join
          <select value={policy} onChange={(e) => setPolicy(e.target.value as JoinPolicy)} className="min-h-[44px] rounded-[10px] border border-white/20 bg-ink px-3 text-fg">
            {(Object.keys(POLICY_LABEL) as JoinPolicy[]).map((p) => (
              <option key={p} value={p}>{POLICY_LABEL[p]}</option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <Button type="submit" variant="primary" disabled={busyId !== null || !domain.trim()}>
            {busyId === "add" ? "Adding..." : "Add domain"}
          </Button>
        </div>
      </form>
      <p className="text-[12px] leading-relaxed text-muted">
        Personal addresses such as Gmail or Outlook cannot be claimed. Automatic joining gives viewer access only, and you need to have signed in with Google in the last 10 minutes to turn it on.
      </p>
      {domains.status === "loading" ? <Skeleton className="h-20" /> : null}
      {domains.status === "error" ? <ErrorState error={domains.error} onRetry={domains.reload} /> : null}
      {domains.status === "ready" && domains.data.length === 0 ? (
        <p className="text-[14px] text-muted">No domains yet. Add your organization&apos;s email domain so colleagues can ask to join.</p>
      ) : null}
      {domains.status === "ready" && domains.data.length > 0 ? (
        <ul className="flex flex-col divide-y divide-white/[.06]" aria-label="Workspace domains">
          {domains.data.map((item) => (
            <li key={item.domain} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-start">
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-[14px] text-fg">
                  <span className="break-all">{item.domain}</span>
                  <Badge tone={item.verified_at ? "ok" : "warn"}>{item.verified_at ? "Verified" : "Not verified yet"}</Badge>
                </p>
                {!item.verified_at && item.verification === "dns_txt" && item.verification_name && item.verification_value ? (
                  <div className="mt-2 flex flex-col gap-1 text-[12px] text-muted">
                    <p>Add this TXT record at your DNS provider, wait a few minutes, then select Verify domain.</p>
                    <p className="break-all">Name: <code className="text-fg-2">{item.verification_name}</code></p>
                    <p className="break-all">Value: <code className="text-fg-2">{item.verification_value}</code></p>
                  </div>
                ) : null}
                {!item.verified_at && item.verification === "google_hd" ? (
                  <p className="mt-1 text-[12px] text-muted">Works while you are signed in with Google using an address at {item.domain}.</p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {!item.verified_at ? (
                  <Button
                    size="sm"
                    variant="primary"
                    disabled={busyId !== null}
                    onClick={() => void run(item.domain, `domain-verify:${item.domain}`, (key) => ws.api.verifyDomain(item.domain, { key }))}
                  >
                    {busyId === item.domain ? "Checking..." : "Verify domain"}
                  </Button>
                ) : (
                  <label className="flex items-center gap-2 text-[12px] text-muted">
                    Who can join
                    <select
                      aria-label={`Who can join from ${item.domain}`}
                      value={item.join_policy}
                      disabled={busyId !== null}
                      onChange={(e) => {
                        const next = e.target.value as JoinPolicy;
                        void run(item.domain, `domain-policy:${item.domain}:${next}`, (key) =>
                          ws.api.updateDomainPolicy(item.domain, { join_policy: next }, { key }),
                        );
                      }}
                      className="min-h-10 rounded-[10px] border border-white/20 bg-ink px-2 text-[13px] text-fg"
                    >
                      {(Object.keys(POLICY_LABEL) as JoinPolicy[]).map((p) => (
                        <option key={p} value={p}>{POLICY_LABEL[p]}</option>
                      ))}
                    </select>
                  </label>
                )}
                <Button size="sm" variant="ghost" disabled={busyId !== null} onClick={() => remove(item)}>
                  Remove
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

const ALL_ROLES: WorkspaceMember["roles"] = ["owner", "admin", "operator", "approver", "viewer"];

/** One member: their roles (editable by owners and admins), remove, or leave for yourself. */
function MemberRow({
  member: m,
  canManage,
  isOwner,
  onChanged,
  onLeft,
}: {
  member: WorkspaceMember;
  canManage: boolean;
  isOwner: boolean;
  onChanged: () => void;
  onLeft: () => void;
}) {
  const ws = useWorkspace();
  const [roles, setRoles] = useState<WorkspaceMember["roles"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const editing = roles !== null;
  const current = roles ?? m.roles;
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      return true;
    } catch (x) {
      setError(describeError(x));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <Avatar name={m.display_name} size={36} />
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] text-fg">
            {m.display_name} {m.you ? <Badge>You</Badge> : null}
          </span>
          <span className="block text-[12px] text-muted">
            {m.email ?? "Address visible to owners and admins"} · joined {relative(m.joined_at)}
          </span>
        </span>
        {!editing ? (
          <span className="flex flex-wrap gap-1.5">
            {m.roles.map((r) => (
              <Badge key={r} tone={r === "approver" ? "warn" : r === "owner" || r === "admin" ? "accent" : "muted"}>{r}</Badge>
            ))}
          </span>
        ) : null}
        <span className="flex gap-1">
          {canManage && !editing ? <Button size="sm" variant="ghost" onClick={() => setRoles(m.roles)}>Change roles</Button> : null}
          {m.you ? (
            <Button size="sm" variant="ghost" disabled={busy} onClick={async () => {
              if (await run(() => ws.api.removeMember(m.id, { key: actionKey("leave") }))) onLeft();
            }}>Leave</Button>
          ) : canManage ? (
            <Button size="sm" variant="ghost" disabled={busy} onClick={async () => {
              if (await run(() => ws.api.removeMember(m.id, { key: actionKey("remove") }))) onChanged();
            }}>Remove</Button>
          ) : null}
        </span>
      </div>
      {editing ? (
        <div className="flex flex-wrap items-center gap-2 pl-12">
          {ALL_ROLES.filter((r) => r !== "owner" || isOwner).map((r) => {
            const on = current.includes(r);
            return (
              <label key={r} className="flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] shadow-[inset_0_0_0_0.8px_var(--app-line)]">
                <input type="checkbox" checked={on} onChange={() => setRoles(on ? current.filter((x) => x !== r) : [...current, r])} /> {r}
              </label>
            );
          })}
          <Button size="sm" variant="primary" disabled={busy || current.length === 0} onClick={async () => {
            if (await run(() => ws.api.updateMember(m.id, current, { key: actionKey("roles") }))) {
              setRoles(null);
              onChanged();
            }
          }}>Save roles</Button>
          <Button size="sm" variant="ghost" onClick={() => setRoles(null)}>Cancel</Button>
        </div>
      ) : null}
      {error ? <p role="alert" className="pl-12 text-[13px] text-bad">{error}</p> : null}
    </li>
  );
}

