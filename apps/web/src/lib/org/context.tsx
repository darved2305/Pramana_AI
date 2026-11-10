"use client";

/**
 * The workspace a page belongs to, resolved from the URL against the signed-in person's own
 * memberships. Pages read the workspace, its roles and a client bound to it from here; they
 * never pick an organization themselves. Authorization still happens in the core on every
 * request: this only decides what to show.
 */
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { organizationApi, type OrganizationApi } from "@/lib/api/organization";
import type { CurrentAccount, OrganizationRole, OrganizationSummary } from "@/lib/api/types";

export interface Workspace {
  org: OrganizationSummary;
  api: OrganizationApi;
  account: CurrentAccount;
  /** Base path of this workspace's pages, for links: ``/app/<slug>``. */
  base: string;
  roles: ReadonlySet<OrganizationRole>;
  /** Owner and admin can run operations; nobody approves unless they hold approver. */
  canOperate: boolean;
  canApprove: boolean;
}

const WorkspaceContext = createContext<Workspace | null>(null);

export function findMembership(account: CurrentAccount, ref: string): OrganizationSummary | null {
  const key = decodeURIComponent(ref).toLowerCase();
  return account.memberships.find((m) => m.slug === key || m.id.toLowerCase() === key) ?? null;
}

export function WorkspaceProvider({
  account,
  org,
  children,
}: {
  account: CurrentAccount;
  org: OrganizationSummary;
  children: ReactNode;
}) {
  const value = useMemo<Workspace>(() => {
    const roles = new Set<OrganizationRole>(org.roles);
    return {
      org,
      api: organizationApi(org.slug),
      account,
      base: `/app/${org.slug}`,
      roles,
      canOperate: roles.has("owner") || roles.has("admin") || roles.has("operator"),
      canApprove: roles.has("approver"),
    };
  }, [account, org]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

/** The current workspace. Only valid inside ``/app/[org]`` pages. */
export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace is only available inside a workspace page");
  return value;
}

/** The current workspace, or null outside ``/app/[org]`` (the shell uses this). */
export function useOptionalWorkspace(): Workspace | null {
  return useContext(WorkspaceContext);
}
