"use client";

import { clsx } from "clsx";
import type { Observation, PackLocation, ParticipantSpec, SitePack } from "@/lib/api/types";
import { IconLock } from "@/components/ui/icons";

/**
 * Building view drawn from the site pack's locations only. Floors stack top-down; on each
 * floor the corridor runs through the middle, rooms sit above it and service spaces
 * (closets, panels, desks) below. Nothing is positioned from invented coordinates: the
 * layout is a function of each location's floor and kind.
 */

const SERVICE = new Set(["closet", "panel", "desk"]);

export type OutcomeTone = "good" | "bad" | "mixed";
const GOOD = new Set(["yes", "on", "connected", "green", "up"]);
const BAD = new Set(["no", "off", "no_network", "tripped", "red"]);
export function outcomeTone(o: string): OutcomeTone {
  if (GOOD.has(o)) return "good";
  if (BAD.has(o)) return "bad";
  return "mixed";
}

export interface MapOverlay {
  participants?: ParticipantSpec[];
  observations?: Observation[];
  affectedId?: string | null;
  /** Location a question is about right now. */
  focusId?: string | null;
  /** Participant currently being asked. */
  askingId?: string | null;
}

export function BuildingMap({
  pack,
  overlay = {},
  selected,
  onSelect,
  compact,
}: {
  pack: SitePack;
  overlay?: MapOverlay;
  selected?: string | null;
  onSelect?: (id: string) => void;
  compact?: boolean;
}) {
  const floors = [...new Set(pack.locations.map((l) => l.floor))].sort((a, b) => b - a);

  return (
    <div className="relative flex flex-col gap-3" role="group" aria-label={`${pack.title}: floor plan`}>
      {floors.map((f) => {
        const locs = pack.locations.filter((l) => l.floor === f);
        const corridors = locs.filter((l) => l.kind === "corridor");
        const rooms = locs.filter((l) => l.kind !== "corridor" && !SERVICE.has(l.kind));
        const service = locs.filter((l) => SERVICE.has(l.kind));
        return (
          <section key={f} aria-label={`Floor ${f}`} className="relative grid grid-cols-[34px_1fr] gap-3">
            <div className="flex flex-col items-center pt-1">
              <span className="display-pixel text-[20px] leading-none text-fg-2">{f}</span>
              <span className="mt-2 w-px flex-1 bg-gradient-to-b from-line-strong to-transparent" aria-hidden />
            </div>
            <div className="rounded-[14px] border-[0.8px] border-line bg-white/[.015] p-2.5">
              <div className={clsx("grid gap-2", compact ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-2 sm:grid-cols-4")}>
                {rooms.map((l) => (
                  <Tile key={l.id} loc={l} overlay={overlay} selected={selected} onSelect={onSelect} compact={compact} />
                ))}
              </div>
              {corridors.map((l) => (
                <div key={l.id} className="mt-2">
                  <Tile loc={l} overlay={overlay} selected={selected} onSelect={onSelect} wide compact={compact} />
                </div>
              ))}
              {service.length ? (
                <div className={clsx("mt-2 grid gap-2", compact ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-2 sm:grid-cols-4")}>
                  {service.map((l) => (
                    <Tile key={l.id} loc={l} overlay={overlay} selected={selected} onSelect={onSelect} compact={compact} />
                  ))}
                </div>
              ) : null}
            </div>
          </section>
        );
      })}
      <Legend />
    </div>
  );
}

function Tile({
  loc,
  overlay,
  selected,
  onSelect,
  wide,
  compact,
}: {
  loc: PackLocation;
  overlay: MapOverlay;
  selected?: string | null;
  onSelect?: (id: string) => void;
  wide?: boolean;
  compact?: boolean;
}) {
  const people = overlay.participants?.filter((p) => p.location_id === loc.id) ?? [];
  const obs = overlay.observations?.filter((o) => o.location_id === loc.id && o.state !== "discarded") ?? [];
  const affected = overlay.affectedId === loc.id;
  const focus = overlay.focusId === loc.id;
  const isSel = selected === loc.id;
  const name = loc.label.replace(/^the /, "");
  const Comp = onSelect ? "button" : "div";

  return (
    <Comp
      {...(onSelect ? { type: "button" as const, onClick: () => onSelect(loc.id), "aria-pressed": isSel } : {})}
      aria-label={`${name}${loc.restricted ? ", restricted" : ""}${people.length ? `, ${people.length} ${people.length === 1 ? "person" : "people"}` : ""}${obs.length ? `, ${obs.length} observations` : ""}${affected ? ", reported affected" : ""}`}
      className={clsx(
        "group relative flex w-full flex-col items-start rounded-[10px] border-[0.8px] text-left transition-[border-color,background-color,box-shadow] duration-300",
        wide ? "min-h-[46px] flex-row items-center gap-3 px-3 py-2" : compact ? "min-h-[64px] p-2.5" : "min-h-[84px] p-3",
        loc.kind === "corridor" ? "bg-white/[.025]" : SERVICE.has(loc.kind) ? "bg-white/[.04]" : "bg-white/[.02]",
        isSel ? "border-accent shadow-[0_0_0_3px_var(--accent-soft)]" : "border-line hover:border-line-strong",
        onSelect && "cursor-pointer",
        focus && !isSel && "border-info/70",
      )}
    >
      {affected ? (
        <span aria-hidden className="pointer-events-none absolute inset-0 rounded-[10px] shadow-[inset_0_0_0_1.5px_var(--accent)]">
          <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-accent pulse-dot" />
        </span>
      ) : null}
      <span className="flex items-center gap-1.5">
        {loc.restricted ? <IconLock className="h-3.5 w-3.5 text-warn" /> : null}
        <span className={clsx("font-medium text-fg", compact ? "text-[12px]" : "text-[13px]", "capitalize")}>{name}</span>
      </span>
      {!wide && !compact ? <span className="mt-0.5 text-[11px] uppercase tracking-[0.06em] text-muted">{loc.kind}</span> : null}
      <span className={clsx("flex flex-wrap items-center gap-1", wide ? "ml-auto" : "mt-auto pt-2")}>
        {obs.slice(-6).map((o) => (
          <span
            key={o.id}
            title={`${o.probe_id.replace(/_/g, " ")}: ${o.outcome.replace(/_/g, " ")}`}
            className={clsx(
              "h-2 w-2 rounded-[2px]",
              outcomeTone(o.outcome) === "good" ? "bg-ok" : outcomeTone(o.outcome) === "bad" ? "bg-bad" : "bg-warn",
              o.state === "superseded" && "opacity-40",
            )}
          />
        ))}
        {people.map((p) => (
          <span
            key={p.id}
            title={p.display_name}
            className={clsx(
              "grid h-5 min-w-5 place-items-center rounded-full px-1 text-[10px] font-semibold",
              overlay.askingId === p.id ? "bg-info text-black" : "bg-white/80 text-black",
            )}
          >
            {p.display_name.slice(0, 1)}
          </span>
        ))}
      </span>
    </Comp>
  );
}

function Legend() {
  return (
    <ul className="ml-[46px] flex flex-wrap gap-x-4 gap-y-1.5 text-[12px] text-muted" aria-label="Legend">
      <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px] bg-ok" /> Working</li>
      <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px] bg-bad" /> Not working</li>
      <li className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px] bg-warn" /> Partial</li>
      <li className="flex items-center gap-1.5"><span className="grid h-4 w-4 place-items-center rounded-full bg-white/80 text-[9px] font-semibold text-black">A</span> Person</li>
      <li className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-[3px] shadow-[inset_0_0_0_1.5px_var(--accent)]" /> Reported area</li>
      <li className="flex items-center gap-1.5"><IconLock className="h-3.5 w-3.5 text-warn" /> Restricted</li>
    </ul>
  );
}
