"use client";

import { useRef, useState } from "react";
import { clsx } from "clsx";
import { Button, Input, Select, Tabs, Textarea } from "@/components/ui";
import { IconPlus, IconTrash } from "@/components/ui/icons";
import type { EquipmentType } from "@/lib/api/types";
import { csvSample, importEquipment } from "@/lib/builder/csv";
import {
  LANGS,
  SKILLS,
  formatNeeds,
  idFrom,
  nameOf,
  parseNeeds,
  withEnglishName,
  type EquipmentSpec,
  type PlaceSpec,
  type RoleSpec,
  type ServicePoint,
  type SiteDescription,
  type Skill,
} from "@/lib/builder/description";

type Tab = "places" | "roles" | "equipment" | "noticed";

const cell = "px-2 py-2 align-top";
const head = "px-2 pb-2 text-left text-[12px] font-medium uppercase tracking-[0.06em] text-muted";
const MAX_CSV_BYTES = 5 * 1024 * 1024;

/** Edits a site description in place. Every change goes through ``onChange``; nothing saves here. */
export function DescriptionEditor({
  value,
  onChange,
  equipment,
  readOnly,
}: {
  value: SiteDescription;
  onChange: (next: SiteDescription) => void;
  equipment: EquipmentType[];
  readOnly?: boolean;
}) {
  const [tab, setTab] = useState<Tab>("equipment");
  const set = (patch: Partial<SiteDescription>) => onChange({ ...value, ...patch });
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[240px] flex-1 flex-col gap-1.5 text-[13px] text-fg-2">
          Site name
          <Input value={value.title} disabled={readOnly} onChange={(e) => set({ title: e.target.value })} />
        </label>
      </div>
      <Tabs
        label="Parts of the site"
        value={tab}
        onChange={setTab}
        items={[
          { value: "places", label: "Places", count: value.places.length },
          { value: "roles", label: "Roles", count: value.roles.length },
          { value: "equipment", label: "Equipment", count: value.equipment.length },
          { value: "noticed", label: "Where problems are noticed", count: value.service_points.length },
        ]}
      />
      <fieldset disabled={readOnly} className="w-full min-w-0">
        {tab === "places" ? <Places value={value} set={set} /> : null}
        {tab === "roles" ? <Roles value={value} set={set} /> : null}
        {tab === "equipment" ? <Equipment value={value} set={set} library={equipment} /> : null}
        {tab === "noticed" ? <Noticed value={value} set={set} /> : null}
      </fieldset>
    </div>
  );
}

type Setter = (patch: Partial<SiteDescription>) => void;

function replaceAt<T>(list: T[], i: number, item: T): T[] {
  return list.map((x, j) => (j === i ? item : x));
}

function Places({ value, set }: { value: SiteDescription; set: Setter }) {
  const update = (i: number, p: PlaceSpec) => set({ places: replaceAt(value.places, i, p) });
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <p className="text-[13px] text-muted">Every place someone could be asked to look. Restricted places list the roles that may enter.</p>
      <div tabIndex={0} role="region" aria-label="Places table" className="relative w-full min-w-0 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
        <table className="w-full min-w-[720px] text-[14px]">
          <thead>
            <tr>
              <th className={head}>Name</th>
              <th className={head}>Floor</th>
              <th className={head}>Kind</th>
              <th className={head}>Who may enter</th>
              <th className={head}><span className="sr-only">Remove</span></th>
            </tr>
          </thead>
          <tbody>
            {value.places.map((p, i) => (
              <tr key={p.id} className="border-t border-white/[.06]">
                <td className={cell}>
                  <Input aria-label="Place name" value={nameOf(p.name)} onChange={(e) => update(i, { ...p, name: withEnglishName(p.name, e.target.value) })} />
                  <span className="mt-1 block font-mono text-[11px] text-muted">{p.id}</span>
                </td>
                <td className={clsx(cell, "w-24")}>
                  <Input aria-label="Floor" type="number" value={p.floor ?? 0} onChange={(e) => update(i, { ...p, floor: Number(e.target.value) || 0 })} />
                </td>
                <td className={clsx(cell, "w-40")}>
                  <Input aria-label="Kind" value={p.kind ?? "room"} onChange={(e) => update(i, { ...p, kind: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })} />
                </td>
                <td className={cell}>
                  <div className="flex flex-wrap gap-1.5">
                    <RoleToggle on={!p.restricted} label="Anyone" onClick={() => update(i, { ...p, restricted: !p.restricted ? true : false, access: p.restricted ? [] : p.access ?? [] })} />
                    {p.restricted
                      ? value.roles.map((r) => {
                          const on = (p.access ?? []).includes(r.id);
                          return (
                            <RoleToggle
                              key={r.id}
                              on={on}
                              label={r.label}
                              onClick={() => update(i, { ...p, access: on ? (p.access ?? []).filter((a) => a !== r.id) : [...(p.access ?? []), r.id] })}
                            />
                          );
                        })
                      : null}
                  </div>
                </td>
                <td className={clsx(cell, "w-12")}>
                  <RemoveButton label={`Remove ${nameOf(p.name)}`} onClick={() => set({ places: value.places.filter((_, j) => j !== i) })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <AddButton
        label="Add a place"
        onClick={() => {
          const id = idFrom("New place", value.places.map((p) => p.id));
          set({ places: [...value.places, { id, name: "the new place", floor: 0, kind: "room" }] });
        }}
      />
    </div>
  );
}

function RoleToggle({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={clsx(
        "h-[30px] rounded-full px-3 text-[12px] transition-colors",
        on ? "bg-accent-soft text-accent shadow-[inset_0_0_0_0.8px_var(--accent-line)]" : "text-muted shadow-[inset_0_0_0_0.8px_var(--app-line)] hover:text-fg",
      )}
    >
      {label}
    </button>
  );
}

function Roles({ value, set }: { value: SiteDescription; set: Setter }) {
  const update = (i: number, r: RoleSpec) => set({ roles: replaceAt(value.roles, i, r) });
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <p className="text-[13px] text-muted">The kinds of people at this site. Skill decides which checks Pramana may ask of them and how much it trusts the answer.</p>
      <ul className="flex flex-col gap-2">
        {value.roles.map((r, i) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2 rounded-[12px] p-3 shadow-[inset_0_0_0_0.8px_var(--app-line)]">
            <Input className="min-w-[180px] flex-1" aria-label="Role name" value={r.label} onChange={(e) => update(i, { ...r, label: e.target.value })} />
            <Select aria-label="Skill" value={r.skill} onChange={(e) => update(i, { ...r, skill: e.target.value as Skill })}>
              {SKILLS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}: {s.hint}
                </option>
              ))}
            </Select>
            <span className="font-mono text-[11px] text-muted">{r.id}</span>
            <RemoveButton label={`Remove ${r.label}`} onClick={() => set({ roles: value.roles.filter((_, j) => j !== i) })} />
          </li>
        ))}
      </ul>
      <AddButton
        label="Add a role"
        onClick={() => set({ roles: [...value.roles, { id: idFrom("role", value.roles.map((r) => r.id), true), skill: "lay", label: "New role" }] })}
      />
    </div>
  );
}

function Equipment({ value, set, library }: { value: SiteDescription; set: Setter; library: EquipmentType[] }) {
  const update = (i: number, e: EquipmentSpec) => set({ equipment: replaceAt(value.equipment, i, e) });
  const byType = new Map(library.map((t) => [t.id, t]));
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <p className="text-[13px] text-muted">
        Add the short IDs of things each item needs to work, separated by commas. Use{" "}
        <code className="font-mono">A | B</code> when either one can do the job, such as a backup pump.
      </p>
      <CsvImport value={value} set={set} library={library} />
      <div tabIndex={0} role="region" aria-label="Equipment table" className="relative w-full min-w-0 max-w-full overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
        <table className="w-full min-w-[860px] text-[14px]">
          <thead>
            <tr>
              <th className={head}>Name</th>
              <th className={head}>Type</th>
              <th className={head}>Where</th>
              <th className={head}>Needs</th>
              <th className={head}><span className="sr-only">Remove</span></th>
            </tr>
          </thead>
          <tbody>
            {value.equipment.map((e, i) => {
              const t = byType.get(e.type);
              return (
                <tr key={e.id} className="border-t border-white/[.06]">
                  <td className={cell}>
                    <Input aria-label="Equipment name" value={nameOf(e.name)} onChange={(ev) => update(i, { ...e, name: withEnglishName(e.name, ev.target.value) })} />
                    <span className="mt-1 block font-mono text-[11px] text-muted">{e.id}</span>
                  </td>
                  <td className={clsx(cell, "w-56")}>
                    <Select aria-label="Type" value={e.type} onChange={(ev) => update(i, { ...e, type: ev.target.value, priors: undefined })}>
                      {library.map((lt) => (
                        <option key={lt.id} value={lt.id}>
                          {lt.label}
                        </option>
                      ))}
                    </Select>
                    {t ? (
                      <span className="mt-1 block text-[11px] leading-snug text-muted">
                        Can fail: {t.failure_modes.map((f) => f.label.replace("{name}", "it")).join("; ") || "no own faults"}
                      </span>
                    ) : null}
                  </td>
                  <td className={clsx(cell, "w-48")}>
                    <Select aria-label="Where" value={e.at} onChange={(ev) => update(i, { ...e, at: ev.target.value })}>
                      {value.places.map((p) => (
                        <option key={p.id} value={p.id}>
                          {nameOf(p.name)}
                        </option>
                      ))}
                    </Select>
                  </td>
                  <td className={cell}>
                    <NeedsInput value={formatNeeds(e.needs)} onCommit={(text) => update(i, { ...e, needs: parseNeeds(text) })} />
                  </td>
                  <td className={clsx(cell, "w-12")}>
                    <RemoveButton label={`Remove ${nameOf(e.name)}`} onClick={() => set({ equipment: value.equipment.filter((_, j) => j !== i) })} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <AddButton
        label="Add equipment"
        onClick={() =>
          set({
            equipment: [
              ...value.equipment,
              {
                id: idFrom("Equipment", value.equipment.map((e) => e.id)),
                type: library[0]?.id ?? "breaker",
                name: "new equipment",
                at: value.places[0]?.id ?? "",
                needs: [],
              },
            ],
          })
        }
      />
    </div>
  );
}

function CsvImport({ value, set, library }: { value: SiteDescription; set: Setter; library: EquipmentType[] }) {
  const [result, setResult] = useState<{ ok: boolean; lines: string[] } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const read = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_CSV_BYTES) {
      setResult({ ok: false, lines: ["This file is too large to import. Choose a CSV file no larger than 5 MB."] });
      return;
    }
    const r = importEquipment(value, await file.text(), library);
    if (!r.description) {
      setResult({ ok: false, lines: r.errors });
      return;
    }
    set({ places: r.description.places, equipment: r.description.equipment });
    setResult({
      ok: true,
      lines: [`Imported: ${r.added} added, ${r.updated} updated, ${r.newPlaces} new places. Save the draft to keep them.`],
    });
  };
  return (
    <div className="flex flex-col gap-2 rounded-[12px] bg-white/[.02] p-3 text-[13px] text-fg-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" onClick={() => input.current?.click()}>
          Import a spreadsheet (CSV)
        </Button>
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          tabIndex={-1}
          aria-label="Import equipment from CSV"
          onChange={(e) => {
            void read(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <a className="underline" download="equipment.csv" href={`data:text/csv;charset=utf-8,${encodeURIComponent(csvSample(library))}`}>
          Download a sample
        </a>
      </div>
      {result ? (
        <div role={result.ok ? "status" : "alert"} aria-label="Import result">
          <ul className={result.ok ? "text-fg" : "text-[var(--app-bad,#f87171)]"}>
            {result.lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** Kept as text while typing so "A |" is not parsed half-way; committed on blur. */
function NeedsInput({ value, onCommit }: { value: string; onCommit: (text: string) => void }) {
  const [text, setText] = useState(value);
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    setSeen(value);
    setText(value);
  }
  return (
    <Input
      aria-label="Needs"
      className="font-mono text-[13px]"
      placeholder="e.g. MAINS, PUMP_A | PUMP_B"
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => onCommit(text)}
    />
  );
}

function Noticed({ value, set }: { value: SiteDescription; set: Setter }) {
  const update = (i: number, s: ServicePoint) => set({ service_points: replaceAt(value.service_points, i, s) });
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-muted">
        What people notice when something is wrong, and which equipment serves each place: water at a tap, cool air from a vent, a card payment at a till.
      </p>
      {value.service_points.map((s, i) => (
        <div key={s.id} className="flex flex-col gap-3 rounded-[14px] p-4 shadow-[inset_0_0_0_0.8px_var(--app-line)]">
          <div className="flex flex-wrap items-center gap-2">
            <Input className="min-w-[220px] flex-1" aria-label="What is noticed" value={s.label} onChange={(e) => update(i, { ...s, label: e.target.value })} />
            <Input className="w-36" aria-label="Outcome when working" value={s.outcomes[0]} onChange={(e) => update(i, { ...s, outcomes: [e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"), s.outcomes[1]] })} />
            <Input className="w-36" aria-label="Outcome when not working" value={s.outcomes[1]} onChange={(e) => update(i, { ...s, outcomes: [s.outcomes[0], e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_")] })} />
            <RemoveButton label={`Remove ${s.label}`} onClick={() => set({ service_points: value.service_points.filter((_, j) => j !== i) })} />
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {LANGS.map((l) => (
              <label key={l.id} className="flex flex-col gap-1 text-[12px] text-fg-2">
                Question in {l.label}
                <Textarea rows={2} value={s.question[l.id] ?? ""} placeholder="In {place}, ...?" onChange={(e) => update(i, { ...s, question: { ...s.question, [l.id]: e.target.value } })} />
              </label>
            ))}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {s.outcomes.map((outcome) => (
              <label key={outcome} className="flex flex-col gap-1 text-[12px] text-fg-2">
                Other ways people say {outcome.replace(/_/g, " ")} (comma separated)
                <NeedsInput
                  value={(s.words?.[outcome] ?? []).join(", ")}
                  onCommit={(text) => {
                    const said = text.split(",").map((w) => w.trim()).filter(Boolean);
                    const words = { ...s.words, [outcome]: said };
                    if (said.length === 0) delete words[outcome];
                    update(i, { ...s, words });
                  }}
                />
              </label>
            ))}
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-[12px] text-fg-2">Served by</span>
            {Object.entries(s.served_by).map(([place, eq]) => (
              <div key={place} className="flex flex-wrap items-center gap-2 text-[13px]">
                <Select aria-label="Place" value={place} onChange={(e) => {
                  const next = { ...s.served_by };
                  delete next[place];
                  next[e.target.value] = eq;
                  update(i, { ...s, served_by: next });
                }}>
                  {value.places.map((p) => (
                    <option key={p.id} value={p.id}>{nameOf(p.name)}</option>
                  ))}
                </Select>
                <span className="text-muted">is served by</span>
                <Select aria-label="Equipment" value={eq} onChange={(e) => update(i, { ...s, served_by: { ...s.served_by, [place]: e.target.value } })}>
                  {value.equipment.map((x) => (
                    <option key={x.id} value={x.id}>{nameOf(x.name)}</option>
                  ))}
                </Select>
                <RemoveButton label="Remove this place" onClick={() => {
                  const next = { ...s.served_by };
                  delete next[place];
                  update(i, { ...s, served_by: next });
                }} />
              </div>
            ))}
            <div>
              <AddButton
                label="Add a place it serves"
                onClick={() => {
                  const free = value.places.find((p) => !(p.id in s.served_by));
                  if (free && value.equipment[0]) update(i, { ...s, served_by: { ...s.served_by, [free.id]: value.equipment[0].id } });
                }}
              />
            </div>
          </div>
        </div>
      ))}
      <AddButton
        label="Add something people notice"
        onClick={() =>
          set({
            service_points: [
              ...value.service_points,
              {
                id: idFrom("noticed", value.service_points.map((s) => s.id), true),
                label: "It works",
                outcomes: ["works", "broken"],
                question: {},
                served_by: value.places[0] && value.equipment[0] ? { [value.places[0].id]: value.equipment[0].id } : {},
              },
            ],
          })
        }
      />
    </div>
  );
}

function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <div>
      <Button size="sm" variant="ghost" type="button" onClick={onClick}>
        <IconPlus /> {label}
      </Button>
    </div>
  );
}

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button size="sm" variant="ghost" type="button" onClick={onClick} aria-label={label}>
      <IconTrash />
    </Button>
  );
}
