"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { Avatar } from "@/components/app/Avatar";
import { ParticipantForm, langLabel, roleLabel } from "@/components/app/ParticipantForm";
import { ConsentDialog, ConsentSummary, EraseDialog } from "@/components/app/PersonPrivacy";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Notice, PageHeader, Select, Skeleton } from "@/components/ui";
import { IconEdit, IconPlus, IconTrash, IconUsers } from "@/components/ui/icons";
import { accountApi, actionKey } from "@/lib/api/account";
import { ApiError, describeError } from "@/lib/api/http";
import type { ConsentRecord, PersonTrackRecord, SitePack, SitePerson } from "@/lib/api/types";
import { packFromDescription, packFromSpec } from "@/lib/builder/sitePack";
import type { SiteDescription } from "@/lib/builder/description";
import { useCursorList, useLoad } from "@/lib/data/hooks";
import { useWorkspace } from "@/lib/org/context";

/** Checks this person could make at this site: their roles allow it and they may go there. */
function reach(pack: SitePack, person: SitePerson["person"]): number {
  const roles = new Set(person.roles);
  const walks = pack.walking_roles.some((r) => roles.has(r));
  const may = (loc: string) => {
    const l = pack.locations.find((x) => x.id === loc);
    return !!l && (!l.restricted || l.access_roles.some((r) => roles.has(r)));
  };
  let n = 0;
  for (const p of pack.probes) {
    if (!p.roles.includes("any") && !p.roles.some((r) => roles.has(r))) continue;
    n += p.locations.filter((loc) => (loc === person.location_id || walks) && may(loc)).length;
  }
  return n;
}

export default function PeoplePage() {
  const ws = useWorkspace();
  const router = useRouter();
  const params = useSearchParams();
  const sites = useCursorList(`sites|${ws.org.id}`, (cursor, s) => ws.api.sites({ limit: 50, cursor }, s));
  const siteRows = useMemo(() => sites.data?.items ?? [], [sites.data]);
  const remembered = ws.account.preferences.last_site_by_org?.[ws.org.id];
  const urlSite = params.get("site");
  const preferred = urlSite ?? remembered;
  const fallbackSite = sites.status === "ready" ? (siteRows.find((s) => s.mode === "live") ?? siteRows[0])?.id : undefined;
  // The chosen site may be beyond the first page of sites, so look it up on its own.
  const preferredLoaded = siteRows.find((s) => s.id === preferred);
  const preferredLookup = useLoad(
    preferred && !preferredLoaded && sites.status === "ready" ? `site|${ws.org.id}|${preferred}` : null,
    (s) => ws.api.site(preferred as string, s),
  );
  // A remembered site that has since gone falls back quietly; a site named in the link does not.
  const rememberedGone = !urlSite && preferredLookup.status === "error";
  const siteId = preferred && !rememberedGone ? preferred : fallbackSite;
  const site =
    siteRows.find((s) => s.id === siteId) ??
    (preferredLookup.status === "ready" && preferredLookup.data.id === siteId ? preferredLookup.data : undefined);

  const people = useCursorList(siteId ? `people|${ws.org.id}|${siteId}` : null, (cursor, s) => ws.api.people(siteId as string, { limit: 25, cursor }, s));
  const list = useMemo(() => (people.status === "ready" ? people.data.items : []), [people]);
  const personKey = list.map((x) => x.person.id).join(",");
  // Track records and consents are fetched only for people not seen yet, so "Load more" adds
  // one page of requests instead of repeating every earlier page.
  const trackCache = useRef(new Map<string, PersonTrackRecord | null>());
  const records = useLoad(siteId && personKey ? `track|${ws.org.id}|${siteId}|${personKey}` : null, async (s) => {
    const cache = trackCache.current;
    const missing = list.map((x) => x.person.id).filter((pid) => !cache.has(`${siteId}|${pid}`));
    for (let i = 0; i < missing.length; i += 100) {
      const part = missing.slice(i, i + 100);
      const page = await ws.api.trackRecord(siteId as string, part, s);
      const found = new Map(page.items.map((r) => [r.person_id, r]));
      part.forEach((pid) => cache.set(`${siteId}|${pid}`, found.get(pid) ?? null));
    }
    return new Map(list.map((x) => [x.person.id, cache.get(`${siteId}|${x.person.id}`) ?? null]));
  });
  const recordOf = (pid: string) => (records.status === "ready" ? (records.data.get(pid) ?? undefined) : undefined);
  // Places and roles come from the published model, or the draft before the first publish.
  const pack = useLoad(site ? `pack|${ws.org.id}|${site.id}|${site.current_model_id}` : null, async (s) => {
    if (!site) return null;
    if (site.current_model_id) return packFromSpec((await ws.api.model(site.id, site.current_model_id, s)).spec);
    try {
      const { draft } = await ws.api.getDraft(site.id, s);
      return packFromDescription(draft.description as unknown as SiteDescription);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  });

  const [editing, setEditing] = useState<"new" | SitePerson | null>(null);
  const [removing, setRemoving] = useState<SitePerson | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [consentFor, setConsentFor] = useState<SitePerson | null>(null);
  const [erasing, setErasing] = useState<SitePerson | null>(null);
  const [erased, setErased] = useState<string | null>(null);
  const canErase = ws.roles.has("owner") || ws.roles.has("admin");
  // A few at a time: this page can list a whole site.
  const consentCache = useRef(new Map<string, ConsentRecord[]>());
  const [consentVersion, setConsentVersion] = useState(0);
  const consents = useLoad(siteId && personKey ? `consents|${ws.org.id}|${siteId}|${personKey}|${consentVersion}` : null, async (s) => {
    const cache = consentCache.current;
    const missing = list.filter((x) => !cache.has(`${siteId}|${x.person.id}`));
    for (let i = 0; i < missing.length; i += 6) {
      const part = missing.slice(i, i + 6);
      const rows = await Promise.all(part.map((x) => ws.api.consents(siteId as string, x.person.id, s)));
      part.forEach((x, n) => cache.set(`${siteId}|${x.person.id}`, rows[n].items));
    }
    return new Map(list.map((x) => [x.person.id, cache.get(`${siteId}|${x.person.id}`) ?? []]));
  });
  const reloadConsents = () => {
    consentCache.current.clear();
    setConsentVersion((v) => v + 1);
  };
  const consentsOf = (pid: string) => (consents.status === "ready" ? consents.data.get(pid) : undefined);
  const sitePack = pack.status === "ready" ? pack.data : null;

  function chooseSite(id: string) {
    router.replace(`${ws.base}/people?site=${id}`);
    accountApi.savePreferences({ last_site: { org_id: ws.org.id, site_id: id } }, actionKey("last-site")).catch(() => undefined);
  }

  return (
    <div className="flex flex-col gap-6 pt-4">
      <PageHeader
        title="People"
        subtitle="Who Pramana can ask at each site, where they usually are and what they may check. Roles come from the site's own model."
        actions={
          <>
            {sites.status === "ready" && (siteRows.length > 1 || sites.data.next_cursor) ? (
              <Select aria-label="Site" value={siteId} onChange={(e) => chooseSite(e.target.value)}>
                {site && !siteRows.some((s) => s.id === site.id) ? <option value={site.id} key={site.id}>{site.name}</option> : null}
                {siteRows.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                    {s.mode === "sandbox" ? " (practice)" : ""}
                  </option>
                ))}
              </Select>
            ) : null}
            {sites.status === "ready" && sites.data.next_cursor ? (
              <Button size="sm" onClick={sites.loadMore} disabled={sites.loadingMore}>{sites.loadingMore ? "Loading..." : "More sites"}</Button>
            ) : null}
            {ws.canOperate && sitePack ? (
              <Button variant="primary" onClick={() => setEditing("new")}>
                <IconPlus /> Add a person
              </Button>
            ) : null}
          </>
        }
      />
      {error ? <Notice tone="bad" title="That did not work">{error}</Notice> : null}
      {urlSite && preferredLookup.status === "error" ? <ErrorState error={preferredLookup.error} onRetry={preferredLookup.reload} /> : null}
      {erased ? <Notice tone="ok" title={`${erased} was erased`}>Past investigations will show them as Erased person.</Notice> : null}

      {sites.status === "error" ? (
        <ErrorState error={sites.error} onRetry={sites.reload} />
      ) : people.status === "loading" || pack.status === "loading" || sites.status === "loading" ? (
        <Skeleton className="h-48" />
      ) : people.status === "error" ? (
        <ErrorState error={people.error} onRetry={people.reload} />
      ) : !sitePack ? (
        <EmptyState
          icon={<IconUsers />}
          title="Describe this site first"
          body="People are placed in the site's own places and given its own roles, so the site needs a model before anyone can be added."
          action={site ? <Link className="text-accent underline" href={`${ws.base}/sites/${site.id}`}>Describe {site.name}</Link> : null}
        />
      ) : list.length === 0 ? (
        <EmptyState
          icon={<IconUsers />}
          title="Nobody listed yet"
          body="Add the guards, technicians and everyday users who could look at something when a problem is reported. The health check uses them to judge the model."
          action={ws.canOperate ? <Button variant="primary" onClick={() => setEditing("new")}><IconPlus /> Add the first person</Button> : null}
        />
      ) : (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {list.map((entry) => {
            const p = entry.person;
            const can = reach(sitePack, p);
            return (
              <Card as="li" key={p.id} className="flex flex-col gap-3 p-4">
                <div className="flex items-center gap-3">
                  <Avatar name={p.display_name} size={40} />
                  <div className="min-w-0">
                    <p className="truncate text-[15px] font-medium text-fg">{p.display_name}</p>
                    <p className="truncate text-[12px] text-muted">
                      {sitePack.locations.find((l) => l.id === p.location_id)?.label ?? p.location_id} · speaks {p.languages.stt_candidates.map(langLabel).join(", ")}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {p.roles.map((r) => (
                    <Badge key={r}>{roleLabel(r, sitePack)}</Badge>
                  ))}
                  {!p.available ? <Badge tone="warn">Unavailable</Badge> : null}
                </div>
                <TrackRecord record={recordOf(p.id)} />
                <ConsentSummary records={consentsOf(p.id)} failed={consents.status === "error"} />
                {sitePack.probes.length ? (
                  <p className="text-[13px] text-fg-2">
                    {can ? `Can make ${can} check${can === 1 ? "" : "s"} at this site.` : "Cannot make any check here yet: give them a role or access to a place."}
                  </p>
                ) : null}
                {ws.canOperate ? (
                  <div className="mt-auto flex flex-wrap gap-2 border-t border-white/[.06] pt-3">
                    <Button size="sm" onClick={() => setEditing(entry)}>
                      <IconEdit className="h-4 w-4" /> Edit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setRemoving(entry)}>
                      <IconTrash className="h-4 w-4" /> Remove
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConsentFor(entry)}>
                      Consent
                    </Button>
                    {canErase ? (
                      <Button size="sm" variant="ghost" onClick={() => { setErased(null); setErasing(entry); }}>
                        Erase
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </Card>
            );
          })}
        </ul>
      )}
      {people.status === "ready" && people.data.next_cursor ? (
        <div className="flex justify-center">
          <Button size="sm" onClick={people.loadMore} disabled={people.loadingMore}>
            {people.loadingMore ? "Loading..." : "Load more people"}
          </Button>
        </div>
      ) : null}
      {people.moreError ? <p role="alert" className="text-[13px] text-bad">Could not load more people. <button className="underline" onClick={people.loadMore}>Try again</button></p> : null}

      <Dialog wide open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "Add a person" : "Edit person"}>
        {editing !== null && sitePack && siteId ? (
          <ParticipantForm
            initial={editing === "new" ? undefined : editing.person}
            pack={sitePack}
            existingIds={list.map((x) => x.person.id)}
            onCancel={() => setEditing(null)}
            onSubmit={async (p) => {
              if (editing === "new") await ws.api.addPerson(siteId, p, { key: actionKey("person") });
              else {
                const { id: _id, ...patch } = p;
                void _id;
                await ws.api.updatePerson(siteId, editing.person.id, patch, editing.version, { key: actionKey("person") });
              }
              people.reload();
              setEditing(null);
            }}
          />
        ) : null}
      </Dialog>

      <Dialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        title={`Remove ${removing?.person.display_name ?? ""}?`}
        description="They will no longer be asked in new investigations at this site. Past investigations keep their record."
        footer={
          <>
            <Button onClick={() => setRemoving(null)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={async () => {
                if (!removing || !siteId) return;
                try {
                  await ws.api.removePerson(siteId, removing.person.id, { key: actionKey("remove") });
                  people.reload();
                  setRemoving(null);
                } catch (e) {
                  setError(describeError(e));
                  setRemoving(null);
                }
              }}
            >
              Remove
            </Button>
          </>
        }
      />

      {siteId ? (
        <>
          <ConsentDialog
            person={consentFor?.person ?? null}
            siteId={siteId}
            api={ws.api}
            records={consentFor ? (consentsOf(consentFor.person.id) ?? []) : []}
            onChanged={reloadConsents}
            onClose={() => setConsentFor(null)}
          />
          <EraseDialog
            person={erasing?.person ?? null}
            siteId={siteId}
            api={ws.api}
            onClose={() => setErasing(null)}
            onErased={(name) => {
              setErasing(null);
              setErased(name);
              people.reload();
            }}
          />
        </>
      ) : null}
    </div>
  );
}

const KIND_LABEL: Record<string, string> = { device: "phone checks", visual: "looking", panel: "reading panels" };

/** Answers matched against causes that were later revealed or confirmed, never Pramana's guess. */
function TrackRecord({ record }: { record: PersonTrackRecord | undefined }) {
  if (!record || record.checked === 0) {
    return <p className="text-[12px] text-muted">No track record yet: it builds up from investigations whose cause was revealed or confirmed.</p>;
  }
  const share = Math.round((100 * record.matched) / record.checked);
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-[13px] text-fg-2">
        <span className="font-medium text-fg">{share}%</span> of {record.checked} answer{record.checked === 1 ? "" : "s"} matched the cause found later, over {record.investigations} investigation{record.investigations === 1 ? "" : "s"}.
      </p>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[.06]" role="img" aria-label={`${record.matched} of ${record.checked} answers matched`}>
        <span className="block h-full bg-ok" style={{ width: `${share}%` }} />
      </div>
      <p className="text-[12px] text-muted">
        {record.by_kind.map((k) => `${KIND_LABEL[k.kind] ?? k.kind}: ${k.matched}/${k.checked}`).join(" · ")}
      </p>
    </div>
  );
}

