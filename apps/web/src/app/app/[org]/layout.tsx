"use client";

import { useParams, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useState } from "react";
import { Button, ButtonLink, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { actionKey } from "@/lib/api/account";
import { describeError } from "@/lib/api/http";
import { organizationApi } from "@/lib/api/organization";
import { refreshAccount, useAccount } from "@/lib/data/account";
import { WorkspaceProvider, findMembership } from "@/lib/org/context";
import type { OrganizationSummary } from "@/lib/api/types";

/** Every page under /app/<workspace>: resolved against the person's own memberships. */
export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  const { org } = useParams<{ org: string }>();
  const account = useAccount();

  if (account.status === "loading" || account.status === "signed-out") {
    // Signed out: the shell is already sending the person to sign in.
    return (
      <div className="flex flex-col gap-4 pt-8" aria-busy="true" aria-label="Loading your workspace">
        <Skeleton className="h-12 w-72" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (account.status === "error") {
    return <ErrorState className="mt-10" error={account.error} onRetry={() => void refreshAccount()} />;
  }
  const membership = findMembership(account.account, org);
  if (!membership) {
    return (
      <EmptyState
        className="mt-10"
        title="You do not have access to this workspace"
        body="It may have been renamed, or your access was removed. Your own workspaces are still available."
        action={<ButtonLink href="/app">Go to my workspaces</ButtonLink>}
      />
    );
  }
  if (membership.deleted_at) return <DeletedWorkspace organization={membership} />;
  return (
    <WorkspaceProvider account={account.account} org={membership}>
      {children}
    </WorkspaceProvider>
  );
}

function longDate(value: string | null | undefined): string {
  if (!value) return "";
  return new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
}

/** Shown instead of the workspace while it waits out its 30-day restore window. */
function DeletedWorkspace({ organization }: { organization: OrganizationSummary }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const owner = organization.roles.includes("owner");
  const api = organizationApi(organization.slug);
  const until = longDate(organization.purge_after);

  async function restore() {
    setBusy(true);
    setError(null);
    try {
      await api.restoreWorkspace({ key: actionKey("restore-workspace") });
      await refreshAccount();
      router.replace(`/app/${organization.slug}`);
    } catch (cause) {
      setError(describeError(cause));
      setBusy(false);
    }
  }

  return (
    <Card className="mx-auto mt-10 flex w-full max-w-2xl flex-col gap-4 p-6">
      <h1 className="text-[20px] font-semibold text-fg">{organization.name} was deleted</h1>
      <p className="text-[14px] leading-relaxed text-fg-2">
        This workspace was deleted on {longDate(organization.deleted_at)}, so it is closed for now.
        {owner
        ? ` You can restore it, with everything in it, until ${until}. After that, people's names, consent records and reports are erased for good.`
          : ` A workspace owner can restore it until ${until}.`}
      </p>
      {owner ? (
        <p className="text-[14px] leading-relaxed text-fg-2">
          The export holds personal data, such as people&apos;s names and what they reported. Keep it somewhere safe.
        </p>
      ) : (
        <p className="text-[14px] leading-relaxed text-fg-2">Ask a workspace owner to restore this workspace if you still need it.</p>
      )}
      {error ? (
        <p role="alert" className="text-[13px] text-bad">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        {owner ? (
          <>
            <Button variant="primary" disabled={busy} onClick={() => void restore()}>
              {busy ? "Restoring..." : "Restore workspace"}
            </Button>
            <ButtonLink href={`/api/core${api.exportHref}`}>Download workspace export</ButtonLink>
          </>
        ) : null}
        <ButtonLink href="/app">Go to my workspaces</ButtonLink>
      </div>
    </Card>
  );
}
