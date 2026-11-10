"use client";

import { useMemo, useState } from "react";
import {
  Badge,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  KeyValue,
  PageHeader,
  PreviewBadge,
  Select,
  Skeleton,
  Tabs,
  Tag,
} from "@/components/ui";
import { IconBuilding } from "@/components/ui/icons";
import { BuildingMap } from "@/components/app/BuildingMap";
import { useDirectory, usePack, usePacks } from "@/lib/data/hooks";
import { roleLabel } from "@/components/app/ParticipantForm";
import { usePreviewMode, usePrefs, prefs } from "@/lib/store/local";

type View = "plan" | "checks" | "decisions";

export default function SitesPage() {
  const preview = usePreviewMode();
  const { defaultPack } = usePrefs();
  const [packId, setPackId] = useState<string>(defaultPack);
  const pack = usePack(packId);
  const packs = usePacks();
  const directory = useDirectory(packId);
  const people = useMemo(() => directory.data?.map((d) => d.participant) ?? [], [directory.data]);
  const [sel, setSel] = useState<string | null>(null);
  const [view, setView] = useState<View>("plan");
  const [reload, setReload] = useState(0);


  const loc = pack.data?.locations.find((l) => l.id === sel);
  const probesHere = pack.data?.probes.filter((p) => !sel || p.locations.length === 0 || p.locations.includes(sel)) ?? [];

  return (
    <div className="flex flex-col gap-5" key={reload}>
      <PageHeader
        title="Sites"
        eyebrow={preview ? <PreviewBadge /> : undefined}
        subtitle="The simulated environment model an investigation reasons about: where things are, who may go where, and what can be checked in each place."
        actions={
          <div className="w-[240px]">
            <label htmlFor="pack" className="sr-only">
              Site model
            </label>
            <Select
              id="pack"
              value={packId}
              onChange={(e) => {
                setPackId(e.target.value);
                prefs.set({ defaultPack: e.target.value });
                setSel(null);
              }}
            >
              {(packs.data ?? [{ id: packId, title: packId }]).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </Select>
          </div>
        }
      />

      {pack.status === "loading" ? (
        <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
          <Skeleton className="h-[460px] rounded-[16px]" />
          <Skeleton className="h-[460px] rounded-[16px]" />
        </div>
      ) : pack.status === "error" ? (
        <Card>
          <ErrorState error={pack.error} onRetry={() => setReload((n) => n + 1)} />
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-[18px] font-medium">{pack.data.title}</h2>
            <Badge>v{pack.data.version}</Badge>
            <Badge tone="info">{pack.data.locations.length} places</Badge>
            <Badge tone="info">{pack.data.probes.length} kinds of check</Badge>
          </div>
          <Tabs<View>
            label="Site view"
            value={view}
            onChange={setView}
            items={[
              { value: "plan", label: "Floor plan" },
              { value: "checks", label: "Checks", count: pack.data.probes.length },
              { value: "decisions", label: "Decisions", count: pack.data.decision_classes.length },
            ]}
          />

          {view === "plan" ? (
            <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
              <Card className="p-4">
                <BuildingMap pack={pack.data} selected={sel} onSelect={(id) => setSel((s) => (s === id ? null : id))} overlay={{ participants: people }} />
              </Card>
              <Card className="p-4 lg:sticky lg:top-4 lg:self-start" aria-live="polite">
                {loc ? (
                  <>
                    <CardHeader title={<span className="capitalize">{loc.label.replace(/^the /, "")}</span>} subtitle={`Floor ${loc.floor} · ${loc.kind}`} />
                    <dl className="mt-3 divide-y divide-line">
                      <KeyValue k="ID" v={<span className="font-mono text-[12px]">{loc.id}</span>} />
                      <KeyValue k="Access" v={loc.restricted ? <Badge tone="warn">Restricted</Badge> : <Badge tone="ok">Open</Badge>} />
                      {loc.restricted ? (
                        <KeyValue k="Who may enter" v={loc.access_roles.map((r) => roleLabel(r, pack.data)).join(", ") || "Nobody listed"} />
                      ) : null}
                      <KeyValue k="People here" v={people.filter((p) => p.location_id === loc.id).map((p) => p.display_name).join(", ") || "Nobody in the directory"} />
                    </dl>
                    <h3 className="mt-5 text-[13px] font-medium text-fg-2">What can be checked here</h3>
                    <ul className="mt-2 flex flex-col gap-2">
                      {probesHere.map((p) => (
                        <li key={p.id} className="rounded-[10px] bg-white/[.03] px-3 py-2">
                          <p className="text-[14px]">{p.label}</p>
                          <p className="mt-0.5 text-[12px] text-muted">
                            Answers: {p.outcomes.map((o) => o.replace(/_/g, " ")).join(" / ")}
                            {p.roles.includes("any") ? "" : ` · needs ${p.roles.map((r) => roleLabel(r, pack.data)).join(" or ")}`}
                          </p>
                        </li>
                      ))}
                      {!probesHere.length ? <li className="text-[13px] text-muted">No checks are defined for this place.</li> : null}
                    </ul>
                  </>
                ) : (
                  <EmptyState icon={<IconBuilding />} title="Select a place" body="Choose any room, corridor or closet on the plan to see who can reach it and what can be checked there." />
                )}
              </Card>
            </div>
          ) : view === "checks" ? (
            <Card className="overflow-hidden">
              <table className="w-full text-left text-[14px]">
                <caption className="sr-only">Checks defined in this site model</caption>
                <thead className="border-b border-line text-[12px] uppercase tracking-[0.06em] text-muted">
                  <tr>
                    <th className="px-4 py-3 font-medium">Check</th>
                    <th className="px-4 py-3 font-medium">Possible answers</th>
                    <th className="hidden px-4 py-3 font-medium md:table-cell">Who</th>
                    <th className="hidden px-4 py-3 font-medium lg:table-cell">Where</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {pack.data.probes.map((p) => (
                    <tr key={p.id}>
                      <td className="px-4 py-3">
                        <p>{p.label}</p>
                        <p className="font-mono text-[11px] text-muted">{p.id}</p>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">{p.outcomes.map((o) => <Tag key={o}>{o.replace(/_/g, " ")}</Tag>)}</div>
                      </td>
                      <td className="hidden px-4 py-3 text-fg-2 md:table-cell">{p.roles.includes("any") ? "Anyone" : p.roles.map((r) => roleLabel(r, pack.data)).join(", ")}</td>
                      <td className="hidden px-4 py-3 text-fg-2 lg:table-cell">{p.locations.length ? `${p.locations.length} places` : "Anywhere"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ) : (
            <Card className="p-2">
              <ul className="divide-y divide-line">
                {pack.data.decision_classes.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-3">
                    <span className="text-[14px]">{d.label}</span>
                    <span className="font-mono text-[11px] text-muted">{d.id}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
