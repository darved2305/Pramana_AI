/**
 * A site description as the builder edits it (the core's ``SiteDescription``). The core
 * validates everything again and lists problems in plain words; these helpers only keep the
 * form convenient.
 */

export type Skill = "lay" | "access" | "technician";
export type Lang = "en" | "hi" | "mr" | "hi-en";
export const LANGS: { id: Lang; label: string }[] = [
  { id: "en", label: "English" },
  { id: "hi", label: "Hindi" },
  { id: "mr", label: "Marathi" },
  { id: "hi-en", label: "Hinglish" },
];

export interface RoleSpec {
  id: string;
  skill: Skill;
  label: string;
}
export interface PlaceSpec {
  id: string;
  name: string | Partial<Record<Lang, string>>;
  floor?: number;
  kind?: string;
  restricted?: boolean;
  access?: string[];
}
export type Need = string | { any_of: string[] };
export interface EquipmentSpec {
  id: string;
  type: string;
  name: string | Partial<Record<Lang, string>>;
  at: string;
  needs?: Need[];
  priors?: Record<string, number>;
}
export interface ServicePoint {
  id: string;
  label: string;
  question: Partial<Record<Lang, string>>;
  outcomes: [string, string];
  served_by: Record<string, string>;
  exec_s?: number;
}
export interface SiteDescription {
  id: string;
  title: string;
  version?: string;
  roles: RoleSpec[];
  places: PlaceSpec[];
  walks?: [string, string, number][] | null;
  equipment: EquipmentSpec[];
  service_points: ServicePoint[];
  no_fault_prior?: number;
  open_world_prior?: number;
}

export const SKILLS: { id: Skill; label: string; hint: string }[] = [
  { id: "lay", label: "Everyday user", hint: "Notices problems where they are" },
  { id: "access", label: "Has access", hint: "Can enter restricted places and look" },
  { id: "technician", label: "Technician", hint: "Can read panels and carry out repairs" },
];

/** ``MCB, PUMP_A | PUMP_B`` <-> ``["MCB", {any_of: ["PUMP_A", "PUMP_B"]}]``. */
export function formatNeeds(needs: Need[] | undefined): string {
  return (needs ?? []).map((n) => (typeof n === "string" ? n : n.any_of.join(" | "))).join(", ");
}
export function parseNeeds(text: string): Need[] {
  return text
    .split(",")
    .map((part) => part.split("|").map((s) => s.trim()).filter(Boolean))
    .filter((alts) => alts.length > 0)
    .map((alts) => (alts.length === 1 ? alts[0] : { any_of: alts }));
}

export function nameOf(name: PlaceSpec["name"]): string {
  return typeof name === "string" ? name : (name.en ?? "");
}
export function withEnglishName(name: PlaceSpec["name"], en: string): PlaceSpec["name"] {
  return typeof name === "string" ? en : { ...name, en };
}

/** An upper-case id from a name: "Pump room" -> "PUMP_ROOM". */
export function idFrom(text: string, taken: string[], lower = false): string {
  const base =
    text
      .normalize("NFKD")
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/[\s-]+/g, "_")
      .slice(0, 40) || "ITEM";
  let id = lower ? base.toLowerCase().replace(/^[^a-z]+/, "") || "item" : base.toUpperCase().replace(/^[^A-Z]+/, "") || "ITEM";
  let n = 2;
  const used = new Set(taken);
  while (used.has(id)) id = `${id.replace(/_\d+$/, "")}_${n++}`;
  return id;
}

export function blankDescription(title: string): SiteDescription {
  return {
    id: idFrom(title, [], true).slice(0, 40) || "my_site",
    title,
    roles: [
      { id: "staff", skill: "lay", label: "Staff" },
      { id: "technician", skill: "technician", label: "Technician" },
    ],
    places: [{ id: "MAIN_HALL", name: "the main hall", floor: 0 }],
    equipment: [],
    service_points: [],
  };
}

/** JSON with object keys sorted, so equal descriptions compare equal whatever their key order
 * (the database stores JSON with its own key order). */
export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableJson(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
