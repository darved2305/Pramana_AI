"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { DescriptionEditor } from "@/components/builder/DescriptionEditor";
import { HealthReport } from "@/components/builder/HealthReport";
import { Badge, Button, ButtonLink, Card, CardHeader, ErrorState, Notice, PageHeader, Skeleton } from "@/components/ui";
import { IconArrowLeft, IconBuilding, IconSpark, IconUsers } from "@/components/ui/icons";
import { actionKey } from "@/lib/api/account";
import { ApiError, describeError } from "@/lib/api/http";
import { libraryApi } from "@/lib/api/library";
import type { SiteModelDraft } from "@/lib/api/types";
import { blankDescription, stableJson, type SiteDescription } from "@/lib/builder/description";
import { relative } from "@/lib/data/derive";
import { useCursorList, useLoad } from "@/lib/data/hooks";
import { useWorkspace } from "@/lib/org/context";

type Busy = null | "save" | "check" | "publish" | "discard" | "start";

export default function SitePage() {
  const ws = useWorkspace();
  const { site: siteId } = useParams<{ site: string }>();
  const suggested = useSearchParams().get("template");
  const site = useLoad(`site|${ws.org.id}|${siteId}`, (s) => ws.api.site(siteId, s));
  const versions = useCursorList(`models|${ws.org.id}|${siteId}`, (cursor, s) => ws.api.models(siteId, { limit: 25, cursor }, s));
  const equipment = useLoad("library|equipment", (s) => libraryApi.equipment(s));
  const templates = useLoad("library|templates", (s) => libraryApi.templates(s));
  const draft = useLoad(`draft|${ws.org.id}|${siteId}`, async (s) => {
    try {
      return await ws.api.getDraft(siteId, s);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  });

  const [desc, setDesc] = useState<SiteDescription | null>(null);
  const [current, setCurrent] = useState<{ draft: SiteModelDraft; etag: string | null } | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [published, setPublished] = useState<number | null>(null);
  const applied = useRef<unknown>(undefined);

  // Take what the core returned as the starting point, once per response. Local edits and
  // saves replace it until the next reload (after publishing, discarding or a conflict).
  const loaded = draft.status === "ready" ? draft.data : undefined;
  useEffect(() => {
    if (loaded === undefined || applied.current === loaded) return;
    applied.current = loaded;
    setCurrent(loaded);
    setDesc(loaded ? (loaded.draft.description as unknown as SiteDescription) : null);
  }, [loaded]);

  const dirty = useMemo(
    () => !!(current && desc && stableJson(desc) !== stableJson(current.draft.description)),
    [current, desc],
  );
  // Leaving with unsaved edits asks first.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function run<T>(what: Busy, fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(what);
    setError(null);
    setProblems([]);
    try {
      return await fn();
    } catch (e) {
      if (e instanceof ApiError && e.problems.length) setProblems(e.problems);
      else setError(describeError(e));
      if (e instanceof ApiError && (e.code === "DRAFT_CHANGED" || e.status === 412)) draft.reload();
      return undefined;
    } finally {
      setBusy(null);
    }
  }

  async function start(body: { template_id: string } | { description: SiteDescription }) {
    const saved = await run("start", () =>
      ws.api.saveDraft(siteId, "template_id" in body ? body : { description: body.description as never }, null, { key: actionKey("draft") }),
    );
    if (saved) {
      setCurrent(saved);
      setDesc(saved.draft.description as unknown as SiteDescription);
      setPublished(null);
    }
  }
  async function save() {
    if (!desc || !current) return;
    const saved = await run("save", () => ws.api.saveDraft(siteId, { description: desc as never }, current.etag, { key: actionKey("draft") }));
    if (saved) {
      setCurrent(saved);
      setDesc(saved.draft.description as unknown as SiteDescription);
    }
  }
  async function check() {
    if (!current) return;
    const checked = await run("check", () => ws.api.checkDraft(siteId, current.draft.id, null, { key: actionKey("health") }));
    if (checked) setCurrent({ draft: checked, etag: `"${checked.spec_sha256}"` });
  }
  async function publish() {
    if (!current) return;
    const done = await run("publish", () => ws.api.publishDraft(siteId, current.draft.id, { key: actionKey("publish") }));
    if (done) {
      setPublished(done.version);
      setCurrent(null);
      setDesc(null);
      site.reload();
      versions.reload();
      draft.reload();
    }
  }
  async function discard() {
    if (!current) return;
    let discarded = false;
    await run("discard", async () => {
      await ws.api.discardDraft(siteId, current.draft.id, { key: actionKey("discard") });
      discarded = true;
    });
    if (discarded) {
      setCurrent(null);
      setDesc(null);
      draft.reload();
    }
  }
  async function editPublished() {
    const s = site.status === "ready" ? site.data : null;
    if (!s?.current_model_id) return;
    const doc = await run("start", () => ws.api.model(siteId, s.current_model_id as string));
    if (doc?.description) await start({ description: doc.description as unknown as SiteDescription });
    else if (doc) setError("This version was not made with the builder. Start from a template instead.");
  }

  if (site.status === "loading" || draft.status === "loading") {
    return (
      <div className="flex flex-col gap-4 pt-4" aria-busy="true" aria-label="Loading the site">
        <Skeleton className="h-12 w-80" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }
  if (site.status === "error") return <ErrorState className="mt-8" error={site.error} onRetry={site.reload} />;
  const s = site.data;
  const live = s.mode === "live";
  const health = current?.draft.health ?? null;
  const canEdit = ws.canOperate && live;

  return (
    <div className="flex flex-col gap-6 pt-4">
      <Link href={`${ws.base}/sites`} className="inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-fg">
        <IconArrowLeft /> All sites
      </Link>
      <PageHeader
        eyebrow={<Badge tone={live ? "accent" : "info"}>{live ? "Your site" : "Practice site"}</Badge>}
        title={desc?.title || s.name}
        subtitle={
          live
            ? "Describe what is here and what depends on what. Pramana works out what can go wrong, who can check it and how to tell causes apart."
            : "A simulated hostel block. Use it to see an investigation end to end before modelling your own site."
        }
        actions={
          <>
            <ButtonLink href={`${ws.base}/people?site=${s.id}`}>
              <IconUsers /> People
            </ButtonLink>
            {s.current_model_id && ws.canOperate ? (
              <ButtonLink href={`${ws.base}/investigations/new?site=${s.id}`} variant="primary">
                {live ? "Practice on this site" : "Run a practice investigation"}
              </ButtonLink>
            ) : null}
          </>
        }
      />

      {published ? <Notice tone="ok" title={`Version ${published} is published`}>New investigations on this site use it. Earlier investigations keep the version they ran on.</Notice> : null}
      {error ? <Notice tone="bad" title="That did not work">{error}</Notice> : null}
      {problems.length ? (
        <Notice tone="bad" title="Fix these first">
          <ul className="mt-1 list-disc pl-5">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Notice>
      ) : null}

      {!live ? (
        <Card className="p-5">
          <CardHeader title="This site cannot be edited" subtitle="It is the same for every workspace, so practice runs can be compared. Build your own site from a template instead." />
        </Card>
      ) : current && desc ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
          <Card className="flex flex-col gap-4 p-5">
            <CardHeader
              title={`Draft, version ${current.draft.version}`}
              subtitle={`${current.draft.counts.places} places · ${current.draft.counts.equipment} pieces of equipment · ${current.draft.counts.checks} checks people can make · ${current.draft.counts.decisions} possible decisions`}
              action={dirty ? <Badge tone="warn">Unsaved changes</Badge> : <Badge tone="ok">Saved</Badge>}
            />
            {equipment.status === "ready" ? (
              <DescriptionEditor value={desc} onChange={setDesc} equipment={equipment.data} readOnly={!canEdit} />
            ) : equipment.status === "error" ? (
              <ErrorState error={equipment.error} onRetry={equipment.reload} />
            ) : (
              <Skeleton className="h-64" />
            )}
            {current.draft.notes?.length ? (
              <Notice tone="warn" title="What could not be generated">
                <ul className="mt-1 list-disc pl-5">
                  {(current.draft.notes ?? []).map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              </Notice>
            ) : null}
            {canEdit ? (
              <div className="flex flex-wrap gap-2 border-t border-white/[.06] pt-4">
                <Button variant="primary" onClick={save} disabled={!dirty || busy !== null}>
                  {busy === "save" ? "Saving..." : "Save draft"}
                </Button>
                <Button variant="ghost" onClick={() => setDesc(current.draft.description as unknown as SiteDescription)} disabled={!dirty || busy !== null}>
                  Undo changes
                </Button>
                <Button variant="danger" className="ml-auto" onClick={discard} disabled={busy !== null}>
                  {busy === "discard" ? "Discarding..." : "Discard draft"}
                </Button>
              </div>
            ) : null}
          </Card>

          <Card className="flex h-fit flex-col gap-4 p-5 xl:sticky xl:top-4">
            <CardHeader
              title="Health check"
              subtitle="Before publishing, Pramana simulates every fault with your people answering, some of them wrongly, and checks it can still find the cause."
            />
            {health ? <HealthReport health={health} /> : <p className="text-[13px] text-muted">{dirty ? "Save your changes, then check them." : "Not checked yet."}</p>}
            {canEdit ? (
              <div className="flex flex-wrap gap-2">
                <Button onClick={check} disabled={dirty || busy !== null}>
                  <IconSpark /> {busy === "check" ? "Checking... (about 10 seconds)" : health ? "Check again" : "Check this model"}
                </Button>
                <Button variant="primary" onClick={publish} disabled={dirty || !health?.ok || busy !== null}>
                  {busy === "publish" ? "Publishing..." : `Publish version ${current.draft.version}`}
                </Button>
              </div>
            ) : null}
          </Card>
        </div>
      ) : (
        <Card className="flex flex-col gap-5 p-5">
          <CardHeader
            title={s.current_model_id ? "Change this site" : "Describe this site"}
            subtitle={
              s.current_model_id
                ? "Edits go into a new draft. The published version stays in use until you publish the new one."
                : "Start from the closest template and change it, or start from scratch."
            }
          />
          {s.current_model_id && canEdit ? (
            <div>
              <Button variant="primary" onClick={editPublished} disabled={busy !== null}>
                {busy === "start" ? "Opening..." : "Edit as a new version"}
              </Button>
            </div>
          ) : null}
          {canEdit ? (
            templates.status === "ready" ? (
              <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {[...templates.data].sort((a, b) => Number(b.id === suggested) - Number(a.id === suggested)).map((t) => (
                  <li key={t.id}>
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => start({ template_id: t.id })}
                      className="flex h-full w-full flex-col gap-2 rounded-[12px] p-4 text-left shadow-[inset_0_0_0_0.8px_var(--app-line)] transition-colors hover:bg-white/[.04] disabled:opacity-50"
                    >
                      <span className="flex items-center gap-2 text-[14px] font-medium text-fg">
                        <IconBuilding aria-hidden /> {t.title}
                        {t.id === suggested ? <Badge tone="accent">Suggested</Badge> : null}
                      </span>
                      <span className="text-[13px] leading-snug text-muted">{t.summary}</span>
                    </button>
                  </li>
                ))}
                <li>
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => start({ description: blankDescription(s.name) })}
                    className="flex h-full w-full flex-col gap-2 rounded-[12px] p-4 text-left shadow-[inset_0_0_0_0.8px_var(--app-line)] transition-colors hover:bg-white/[.04] disabled:opacity-50"
                  >
                    <span className="text-[14px] font-medium text-fg">Start from scratch</span>
                    <span className="text-[13px] leading-snug text-muted">An empty site with one place and two roles.</span>
                  </button>
                </li>
              </ul>
            ) : templates.status === "error" ? (
              <ErrorState error={templates.error} onRetry={templates.reload} />
            ) : (
              <Skeleton className="h-28" />
            )
          ) : (
            <p className="text-[13px] text-muted">Ask an operator or owner of this workspace to describe the site.</p>
          )}
        </Card>
      )}

      <Card className="p-5">
        <CardHeader title="Published versions" subtitle="Each investigation keeps the exact version it ran on, so its replay never changes." />
        {versions.status === "ready" ? (
            versions.data.items.length ? (
            <ul className="mt-3 flex flex-col divide-y divide-white/[.06] text-[14px]">
              {versions.data.items.map((v) => (
                <li key={v.id} className="flex items-center gap-3 py-2.5">
                  <span className="font-medium text-fg">Version {v.version}</span>
                  <Badge tone={v.status === "published" ? "ok" : "muted"}>{v.status === "published" ? "In use" : "Retired"}</Badge>
                  <span className="ml-auto text-[12px] text-muted">{v.published_at ? `published ${relative(v.published_at)}` : ""}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-[13px] text-muted">Nothing published yet.</p>
          )
        ) : versions.status === "error" ? (
          <ErrorState error={versions.error} onRetry={versions.reload} />
        ) : (
          <Skeleton className="mt-3 h-16" />
        )}
        {versions.status === "ready" && versions.data.next_cursor ? (
          <div className="mt-3"><Button size="sm" onClick={versions.loadMore} disabled={versions.loadingMore}>{versions.loadingMore ? "Loading..." : "Load more versions"}</Button></div>
        ) : null}
        {versions.moreError ? <p role="alert" className="mt-3 text-[13px] text-bad">Could not load more versions. <button className="underline" onClick={versions.loadMore}>Try again</button></p> : null}
      </Card>
    </div>
  );
}
