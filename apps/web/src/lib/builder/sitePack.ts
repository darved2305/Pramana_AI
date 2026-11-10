/**
 * The small site view the console's forms and map read (places, roles, checks), built from a
 * stored model's spec or, before the first publish, from the draft's description.
 */
import type { PackLocation, PackRole, SitePack } from "@/lib/api/types";
import { nameOf, type SiteDescription } from "./description";

const BUILTIN_ROLES: PackRole[] = [
  { id: "student", label: "Student", skill: "lay" },
  { id: "guard", label: "Security guard", skill: "access" },
  { id: "electrician", label: "Electrician", skill: "technician" },
  { id: "it_tech", label: "IT technician", skill: "technician" },
  { id: "housekeeping", label: "Housekeeping", skill: "access" },
];

type Spec = Record<string, unknown> & {
  pack?: string;
  version?: string;
  title?: string;
  roles?: PackRole[] | null;
  locations?: { id: string; floor: number; kind: string; label: { en: string }; restricted?: boolean; access_roles?: string[] }[];
  probes?: { id: string; label: string; outcomes: string[]; roles: string[]; observes: { at: string }[] }[];
  decision_classes?: { id: string; label: string }[];
  walking_roles?: string[];
};

export function packFromSpec(raw: Record<string, unknown>): SitePack {
  const spec = raw as Spec;
  return {
    id: spec.pack ?? "site",
    version: spec.version ?? "",
    title: spec.title ?? "",
    locations: (spec.locations ?? []).map(
      (l): PackLocation => ({
        id: l.id,
        floor: l.floor,
        kind: l.kind,
        label: l.label.en,
        restricted: !!l.restricted,
        access_roles: l.access_roles ?? [],
      }),
    ),
    probes: (spec.probes ?? []).map((p) => ({
      id: p.id,
      label: p.label,
      outcomes: p.outcomes,
      roles: p.roles,
      locations: p.observes.map((b) => b.at),
    })),
    decision_classes: (spec.decision_classes ?? []).map((d) => ({ id: d.id, label: d.label })),
    walking_roles: spec.walking_roles ?? [],
    roles: spec.roles ?? BUILTIN_ROLES,
  };
}

export function packFromDescription(d: SiteDescription): SitePack {
  return {
    id: d.id,
    version: d.version ?? "",
    title: d.title,
    locations: d.places.map((p) => ({
      id: p.id,
      floor: p.floor ?? 0,
      kind: p.kind ?? "room",
      label: nameOf(p.name),
      restricted: !!p.restricted,
      access_roles: p.access ?? [],
    })),
    probes: [],
    decision_classes: [],
    walking_roles: d.roles.filter((r) => r.skill !== "lay").map((r) => r.id),
    roles: d.roles.map((r) => ({ id: r.id, label: r.label, skill: r.skill })),
  };
}
