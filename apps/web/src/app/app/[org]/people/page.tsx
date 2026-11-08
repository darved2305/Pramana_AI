"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Avatar } from "@/components/app/Avatar";
import { ParticipantForm, langLabel, roleLabel } from "@/components/app/ParticipantForm";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Notice, PageHeader, Select, Skeleton } from "@/components/ui";
import { IconEdit, IconPlus, IconTrash, IconUsers } from "@/components/ui/icons";
import { accountApi, actionKey } from "@/lib/api/account";
import { ApiError, describeError } from "@/lib/api/http";
import type { SitePack, SitePerson } from "@/lib/api/types";
import { packFromDescription, packFromSpec } from "@/lib/builder/sitePack";
import type { SiteDescription } from "@/lib/builder/description";
import { useLoad } from "@/lib/data/hooks";
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
  const sites = useLoad(`sites|${ws.org.id}`, (s) => ws.api.sites(s));
  const remembered = ws.account.preferences.last_site_by_org?.[ws.org.id];
  const siteId =
    params.get("site") ??
    (sites.status === "ready"
      ? (sites.data.find((s) => s.id === remembered) ?? sites.data.find((s) => s.mode === "live") ?? sites.data[0])?.id
      : undefined);
  const site = sites.status === "ready" ? sites.data.find((s) => s.id === siteId) : undefined;

  const people = useLoad(siteId ? `people|${ws.org.id}|${siteId}` : null, (s) => ws.api.people(siteId as string, s));
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
  const list = useMemo(() => (people.status === "ready" ? people.data : []), [people]);
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
            {sites.status === "ready" && sites.data.length > 1 ? (
              <Select aria-label="Site" value={siteId} onChange={(e) => chooseSite(e.target.value)}>
                {sites.data.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                    {s.mode === "sandbox" ? " (practice)" : ""}
                  </option>
                ))}
              </Select>
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
                {sitePack.probes.length ? (
                  <p className="text-[13px] text-fg-2">
                    {can ? `Can make ${can} check${can === 1 ? "" : "s"} at this site.` : "Cannot make any check here yet: give them a role or access to a place."}
                  </p>
                ) : null}
                {ws.canOperate ? (
                  <div className="mt-auto flex gap-2 border-t border-white/[.06] pt-3">
                    <Button size="sm" onClick={() => setEditing(entry)}>
                      <IconEdit className="h-4 w-4" /> Edit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setRemoving(entry)}>
                      <IconTrash className="h-4 w-4" /> Remove
                    </Button>
                  </div>
                ) : null}
              </Card>
            );
          })}
        </ul>
      )}

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
    </div>
  );
}
