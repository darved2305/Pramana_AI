/**
 * Import equipment from an asset register exported as CSV. Nothing is applied unless every row
 * can be read; the core still validates the whole description when the draft is saved.
 */

import type { EquipmentSpec, Need, PlaceSpec, SiteDescription } from "./description";
import { idFrom, nameOf } from "./description";

const ALIASES: Record<string, string[]> = {
  name: ["name", "asset", "asset name", "equipment"],
  type: ["type", "equipment type", "asset type", "class"],
  location: ["location", "place", "room", "area"],
  floor: ["floor", "level"],
  depends_on: ["depends_on", "depends on", "needs", "parent", "fed by"],
};

/** RFC 4180 rows: quoted fields may hold commas, doubled quotes and line breaks. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  const src = text.replace(/^﻿/, "");
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (quoted) {
      if (c === '"' && src[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && src[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += c;
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => r.some((f) => f.trim() !== ""));
}

const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");

export interface CsvResult {
  description: SiteDescription | null;
  errors: string[];
  added: number;
  updated: number;
  newPlaces: number;
}

/** A sample register that uses types from the site's own equipment library. */
export function csvSample(library: { id: string }[]): string {
  const type = library[0]?.id ?? "breaker";
  return `name,type,location,floor,depends_on\nFirst unit,${type},Plant room,0,\nBackup unit,${type},Plant room,0,\nDownstream unit,${type},Terrace,4,First unit | Backup unit\n`;
}

/** Merge a register into a description. A row whose name is already listed updates that item. */
export function importEquipment(
  value: SiteDescription,
  text: string,
  library: { id: string; label: string }[],
): CsvResult {
  const fail = (errors: string[]): CsvResult => ({ description: null, errors, added: 0, updated: 0, newPlaces: 0 });
  const [header, ...rows] = parseCsv(text);
  if (!header || rows.length === 0) return fail(["The file has no rows below its header."]);
  const col: Record<string, number> = {};
  for (const [key, names] of Object.entries(ALIASES)) {
    const at = header.findIndex((h) => names.includes(norm(h)));
    if (at >= 0) col[key] = at;
  }
  const absent = ["name", "type", "location"].filter((k) => col[k] === undefined);
  if (absent.length > 0) return fail([`Missing column: ${absent.join(", ")}.`]);

  const types = new Map<string, string>();
  for (const t of library) {
    types.set(norm(t.id), t.id);
    types.set(norm(t.label), t.id);
  }
  const errors: string[] = [];
  const places: PlaceSpec[] = [...value.places];
  const equipment: EquipmentSpec[] = [...value.equipment];
  const seen = new Set<string>();
  const pending: { item: number; line: number; needs: string }[] = [];
  let added = 0;
  let updated = 0;
  const get = (r: string[], key: string) => (col[key] === undefined ? "" : (r[col[key]] ?? "").trim());

  rows.forEach((r, n) => {
    const line = n + 2;
    const name = get(r, "name");
    const typeText = get(r, "type");
    const location = get(r, "location");
    if (!name || !location || !typeText) {
      errors.push(`Row ${line}: name, type and location are all needed.`);
      return;
    }
    if (seen.has(norm(name))) {
      errors.push(`Row ${line}: "${name}" is listed twice.`);
      return;
    }
    seen.add(norm(name));
    const type = types.get(norm(typeText));
    if (!type) {
      errors.push(`Row ${line}: unknown equipment type "${typeText}".`);
      return;
    }
    const floorText = get(r, "floor");
    if (floorText !== "" && !/^-?\d+$/.test(floorText)) {
      errors.push(`Row ${line}: floor "${floorText}" is not a whole number.`);
      return;
    }
    let place = places.find((p) => norm(nameOf(p.name)) === norm(location) || norm(p.id) === norm(location));
    if (!place) {
      place = { id: idFrom(location, places.map((p) => p.id)), name: location, floor: floorText ? Number(floorText) : 0 };
      places.push(place);
    }
    let item = equipment.findIndex((e) => norm(nameOf(e.name)) === norm(name) || norm(e.id) === norm(name));
    if (item >= 0) {
      equipment[item] = { ...equipment[item], type, at: place.id };
      updated++;
    } else {
      item = equipment.length;
      equipment.push({ id: idFrom(name, equipment.map((e) => e.id)), type, name, at: place.id, needs: [] });
      added++;
    }
    pending.push({ item, line, needs: get(r, "depends_on") });
  });

  const resolve = (ref: string, line: number): string | null => {
    const hit = equipment.find((e) => norm(nameOf(e.name)) === norm(ref) || norm(e.id) === norm(ref));
    if (!hit) errors.push(`Row ${line}: depends on "${ref}", which is not listed.`);
    return hit?.id ?? null;
  };
  for (const { item, line, needs } of pending) {
    if (!needs) continue;
    const parsed: Need[] = [];
    for (const part of needs.split(/[,;]/).map((s) => s.trim()).filter(Boolean)) {
      const ids = part.split("|").map((s) => resolve(s.trim(), line)).filter((id): id is string => id !== null);
      if (ids.length > 1) parsed.push({ any_of: ids });
      else if (ids.length === 1) parsed.push(ids[0]);
    }
    equipment[item] = { ...equipment[item], needs: parsed };
  }
  if (errors.length > 0) return fail(errors);
  return { description: { ...value, places, equipment }, errors: [], added, updated, newPlaces: places.length - value.places.length };
}
