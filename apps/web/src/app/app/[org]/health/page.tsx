"use client";

import Link from "next/link";
import { HealthReport } from "@/components/builder/HealthReport";
import { Badge, Button, ButtonLink, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui";
import { IconChart } from "@/components/ui/icons";
import type { ModelHealth, SiteSummary } from "@/lib/api/types";
import { useCursorList, useLoad } from "@/lib/data/hooks";
import { useWorkspace } from "@/lib/org/context";

interface SiteHealth {
  site: SiteSummary;
  version: number | null;
  health: ModelHealth | null;
}

function summary(h: ModelHealth) {
  const runs = h.faults.filter((f) => f.reportable && f.episodes > 0);
  const total = runs.reduce((n, f) => n + f.episodes, 0);
  const right = runs.reduce((n, f) => n + f.correct, 0);
  const wrong = runs.reduce((n, f) => n + f.wrong, 0);
  return { faults: runs.length, right: total ? right / total : null, wrong: total ? wrong / total : null };
}

/** Each published model with the check it passed: what Pramana can and cannot tell apart. */
export default function ModelHealthPage() {
  const ws = useWorkspace();
  const sites = useCursorList(`health-sites|${ws.org.id}`, (cursor, signal) => ws.api.sites({ limit: 25, cursor }, signal));
  const siteRows = sites.data?.items ?? [];
  const siteKey = siteRows.map((site) => site.id).join(",");
  // Waits for the site page; an empty workspace still resolves to an empty list.
  const load = useLoad(sites.status === "ready" ? `health|${ws.org.id}|${siteKey}` : null, async (signal): Promise<SiteHealth[]> => {
    return Promise.all(
      siteRows.map(async (site) => {
        if (!site.current_model_id) return { site, version: null, health: null };
        const doc = await ws.api.model(site.id, site.current_model_id, signal);
        return { site, version: doc.version, health: doc.health ?? null };
      }),
    );
  });

  return (
    <div className="flex flex-col gap-6 pt-4">
      <PageHeader
        title="Model health"
        subtitle="For every site, what its people and checks can tell apart, and how often a simulated investigation reaches the right decision when some answers are wrong. Holding back is the right answer when a cause cannot be told apart."
      />
      {sites.status === "error" ? (
        <ErrorState error={sites.error} onRetry={sites.reload} />
      ) : sites.status === "loading" || load.status === "loading" ? (
        <Skeleton className="h-64" />
      ) : load.status === "error" ? (
        <ErrorState error={load.error} onRetry={load.reload} />
      ) : load.data.length === 0 ? (
        <EmptyState icon={<IconChart />} title="No sites yet" />
      ) : (
        [...load.data]
          // Sites that need attention first: unchecked, then failing, then healthy.
          .sort((a, b) => rank(a) - rank(b))
          .map(({ site, version, health }) => {
            const s = health ? summary(health) : null;
            return (
              <Card key={site.id} className="flex flex-col gap-4 p-5">
                <CardHeader
                  title={
                    <span className="flex flex-wrap items-center gap-2">
                      <Link href={`${ws.base}/sites/${site.id}`} className="hover:underline">{site.name}</Link>
                      <Badge tone={site.mode === "sandbox" ? "info" : "accent"}>{site.mode === "sandbox" ? "Practice" : "Your site"}</Badge>
                      {version ? <Badge>Version {version}</Badge> : null}
                    </span>
                  }
                  subtitle={
                    !version
                      ? "Not described yet."
                      : health && s
                        ? `${s.faults} faults simulated · ${s.right != null ? Math.round(s.right * 100) : "-"}% right · ${s.wrong != null ? Math.round(s.wrong * 100) : "-"}% wrong`
                        : site.mode === "sandbox"
                          ? "The shared practice model is the same for every workspace and is checked by the benchmark, not here."
                          : "This version was published without a stored check."
                  }
                  action={
                    site.mode === "live" && ws.canOperate ? (
                      <ButtonLink size="sm" href={`${ws.base}/sites/${site.id}`}>{version ? "Change and re-check" : "Describe it"}</ButtonLink>
                    ) : null
                  }
                />
                {health ? <HealthReport health={health} /> : null}
              </Card>
            );
          })
      )}
      {sites.status === "ready" && sites.data.next_cursor ? (
        <div className="flex justify-center"><Button size="sm" onClick={sites.loadMore} disabled={sites.loadingMore}>{sites.loadingMore ? "Loading..." : "Load more sites"}</Button></div>
      ) : null}
      {sites.moreError ? <p role="alert" className="text-[13px] text-bad">Could not load more sites. <button className="underline" onClick={sites.loadMore}>Try again</button></p> : null}
    </div>
  );
}

function rank(x: SiteHealth): number {
  if (x.site.mode === "sandbox") return 3;
  if (!x.version) return 0;
  if (!x.health) return 1;
  return x.health.ok ? 2 : 1;
}
