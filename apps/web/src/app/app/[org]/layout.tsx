"use client";

import { useParams } from "next/navigation";
import type { ReactNode } from "react";
import { ButtonLink, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { refreshAccount, useAccount } from "@/lib/data/account";
import { WorkspaceProvider, findMembership } from "@/lib/org/context";

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
  return (
    <WorkspaceProvider account={account.account} org={membership}>
      {children}
    </WorkspaceProvider>
  );
}
