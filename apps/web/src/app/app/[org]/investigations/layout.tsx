"use client";

import type { ReactNode } from "react";
import { InvestigationScopeProvider } from "@/lib/data/scope";
import { useWorkspace } from "@/lib/org/context";

/** Investigation screens inside a workspace: every call goes to /v1/orgs/<workspace>/... */
export default function WorkspaceInvestigationsLayout({ children }: { children: ReactNode }) {
  const ws = useWorkspace();
  return <InvestigationScopeProvider api={ws.api}>{children}</InvestigationScopeProvider>;
}
