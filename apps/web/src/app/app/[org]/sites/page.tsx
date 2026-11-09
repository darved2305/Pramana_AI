"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";
import { Badge, Button, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { IconBuilding, IconChevronRight } from "@/components/ui/icons";
import { useCursorList } from "@/lib/data/hooks";
import { useWorkspace } from "@/lib/org/context";

export default function SitesPage() {
  const ws = useWorkspace();
  const sites = useCursorList(`sites|${ws.org.id}`, (cursor, s) => ws.api.sites({ limit: 25, cursor }, s));
  const rows = useMemo(() => sites.data?.items ?? [], [sites.data]);
  const router = useRouter();
  const suggested = useSearchParams().get("template");
  // Coming from setup with a suggested template: open the one site still to describe.
  useEffect(() => {
    if (!suggested || sites.status !== "ready") return;
    const empty = rows.filter((s) => s.mode === "live" && !s.current_model_id);
    if (empty.length === 1) router.replace(`${ws.base}/sites/${empty[0].id}?template=${encodeURIComponent(suggested)}`);
  }, [suggested, sites, rows, router, ws.base]);
  return (
    <div className="flex flex-col gap-6 pt-4">
      <PageHeader
        title="Sites"
        subtitle="Each site has its own model: what is there, what depends on what, and who can check it. Investigations always run on a published version."
      />
      {sites.status === "loading" ? (
        <Skeleton className="h-40" />
      ) : sites.status === "error" ? (
        <ErrorState error={sites.error} onRetry={sites.reload} />
      ) : rows.length === 0 ? (
        <EmptyState title="No sites yet" body="Sites are created with the workspace." icon={<IconBuilding />} />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {rows.map((s) => (
            <li key={s.id}>
              <Link href={`${ws.base}/sites/${s.id}`} className="card group flex h-full items-start gap-4 p-5 transition-colors hover:bg-white/[.03]">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-[12px] bg-accent-soft text-accent">
                  <IconBuilding />
                </span>
                <span className="flex min-w-0 flex-1 flex-col gap-1.5">
                  <span className="text-[16px] font-medium text-fg">
                    {s.mode === "sandbox" ? "Practice site (simulated)" : s.name}
                  </span>
                  <span className="flex flex-wrap gap-1.5">
                    <Badge tone={s.mode === "sandbox" ? "info" : "accent"}>{s.mode === "sandbox" ? "Practice" : "Your site"}</Badge>
                    {s.current_model_id ? <Badge tone="ok">Published</Badge> : <Badge>Not described yet</Badge>}
                  </span>
                  <span className="text-[13px] text-muted">
                    {s.mode === "sandbox"
                      ? "A simulated site for guided practice runs."
                      : s.current_model_id
                        ? "Open to change its model or practise on it."
                        : "Describe it from a template to start investigating here."}
                  </span>
                </span>
                <IconChevronRight className="mt-1 text-muted transition-transform group-hover:translate-x-0.5" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      )}
      {sites.status === "ready" && sites.data.next_cursor ? (
        <div className="flex justify-center">
          <Button size="sm" onClick={sites.loadMore} disabled={sites.loadingMore}>
            {sites.loadingMore ? "Loading..." : "Load more sites"}
          </Button>
        </div>
      ) : null}
      {sites.moreError ? <p role="alert" className="text-[13px] text-bad">Could not load more sites. <button className="underline" onClick={sites.loadMore}>Try again</button></p> : null}
    </div>
  );
}
