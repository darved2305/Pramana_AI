"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Avatar } from "@/components/app/Avatar";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, KeyValue, Notice, PageHeader, Skeleton } from "@/components/ui";
import { IconCopy } from "@/components/ui/icons";
import { actionKey } from "@/lib/api/account";
import { describeError } from "@/lib/api/http";
import type { CreateInvitation, InvitationCreated, WorkspaceMember } from "@/lib/api/types";
import { refreshAccount } from "@/lib/data/account";
import { relative } from "@/lib/data/derive";
import { useLoad } from "@/lib/data/hooks";
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
  const members = useLoad(`members|${ws.org.id}`, (s) => ws.api.members(s));
  const invitations = useLoad(canManage ? `invitations|${ws.org.id}` : null, (s) => ws.api.invitations(s));
  const [email, setEmail] = useState("");
  const [roles, setRoles] = useState<InvitedRole[]>(["operator"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<{ id: string; email: string; url: string; delivery: InvitationCreated["email_delivery"] } | null>(null);
  const [copied, setCopied] = useState(false);

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

      <Card className="flex flex-col gap-4 p-5">
        <CardHeader title="Members" subtitle="People with an account here. The people asked during investigations are listed per site under People." />
        {members.status === "loading" ? <Skeleton className="h-24" /> : null}
        {members.status === "error" ? <ErrorState error={members.error} onRetry={members.reload} /> : null}
        {members.status === "ready" ? (
          <ul className="flex flex-col divide-y divide-white/[.06]" aria-label="Members">
            {members.data.map((m) => (
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
      </Card>

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
          {invitations.status === "ready" && invitations.data.length ? (
            <ul className="flex flex-col divide-y divide-white/[.06]" aria-label="Invitations">
              {invitations.data.map((i) => (
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
        </Card>
      ) : null}

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

