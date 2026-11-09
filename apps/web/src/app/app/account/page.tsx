"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, ButtonLink, Card, CardHeader, KeyValue, Notice, PageHeader } from "@/components/ui";
import { IconUser } from "@/components/ui/icons";
import { auth } from "@/lib/api/auth";
import { describeError } from "@/lib/api/http";
import { clock } from "@/lib/data/derive";
import { setSession, useSession } from "@/lib/data/session";
import { usePreviewMode } from "@/lib/store/local";

const ROLE_TEXT: Record<string, string> = {
  operator: "Operator: starts investigations, manages participants, requests repairs.",
  approver: "Approver: approves or denies repairs. The decision records this account.",
};

export default function AccountPage() {
  const session = useSession();
  const preview = usePreviewMode();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const me = session.status === "signed-in" ? session.session : null;

  const signOut = async () => {
    setBusy(true);
    setErr(null);
    try {
      await auth.signOut();
      setSession(null);
      router.replace("/login");
    } catch (e) {
      setErr(describeError(e));
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Account" />
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card className="p-5">
          <div className="flex items-center gap-4">
            <span className="grid h-16 w-16 place-items-center rounded-full bg-white/[.06] text-fg-2">
              <IconUser className="h-7 w-7" />
            </span>
            <div>
              <p className="text-[18px] font-medium">{me ? me.displayName : preview ? "Preview" : "Not signed in"}</p>
              <p className="text-[14px] text-muted">
                {me?.method === "open" ? "Sign-in is not required here." : me ? me.email : preview ? "Sample data, no account." : ""}
              </p>
            </div>
          </div>
          <dl className="mt-5 divide-y divide-line">
            <KeyValue k="Account ID" v={me ? <span className="font-mono text-[12px]">{me.userId}</span> : <span className="text-muted">None</span>} />
            <KeyValue
              k="Roles"
              v={
                me ? (
                  <span className="flex flex-wrap justify-end gap-1.5">
                    {me.roles.map((r) => (
                      <Badge key={r} tone="info">
                        {r}
                      </Badge>
                    ))}
                  </span>
                ) : (
                  <span className="text-muted">None</span>
                )
              }
            />
            <KeyValue k="Session ends" v={me && me.method === "session" ? clock(me.expiresAt) : <span className="text-muted">Not applicable</span>} />
          </dl>
          {err ? (
            <Notice tone="bad" className="mt-4">
              {err}
            </Notice>
          ) : null}
          <div className="mt-5 flex gap-2">
            {me && me.method === "session" ? (
              <Button variant="danger" onClick={signOut} disabled={busy}>
                Sign out
              </Button>
            ) : (
              <ButtonLink href="/login">Sign in</ButtonLink>
            )}
          </div>
        </Card>
        <Card className="p-5">
          <CardHeader title="What your roles allow" />
          <ul className="mt-3 flex flex-col gap-2 text-[14px] text-fg-2">
            {(me?.roles ?? ["operator", "approver"]).map((r) => (
              <li key={r}>{ROLE_TEXT[r] ?? r}</li>
            ))}
          </ul>
          <Notice className="mt-4">
            Accounts are created by a site operator. Participants do not sign in: each gets a personal link from the
            investigation, which only works for their own questions.
          </Notice>
        </Card>
      </div>
    </div>
  );
}
