"use client";

import { useState } from "react";
import { clsx } from "clsx";
import { Button, Checkbox, Field, Input, Select, Switch } from "@/components/ui";
import type { ParticipantSpec, Role, SitePack, Skill, SttLanguage, TemplateLanguage } from "@/lib/api/types";

export const ROLES: { value: Role; label: string }[] = [
  { value: "student", label: "Student or resident" },
  { value: "guard", label: "Security guard" },
  { value: "electrician", label: "Electrician" },
  { value: "it_tech", label: "IT technician" },
  { value: "housekeeping", label: "Housekeeping" },
];

export const SKILLS: { value: Skill; label: string; hint: string }[] = [
  { value: "lay", label: "Everyday user", hint: "Can describe what they see and use a phone." },
  { value: "access", label: "Has access", hint: "Can enter restricted rooms such as network closets." },
  { value: "technician", label: "Technician", hint: "Can inspect and operate equipment." },
];

export const STT_LANGS: { value: SttLanguage; label: string }[] = [
  { value: "hi-IN", label: "Hindi" },
  { value: "mr-IN", label: "Marathi" },
  { value: "en-IN", label: "English (India)" },
  { value: "bn-IN", label: "Bengali" },
  { value: "gu-IN", label: "Gujarati" },
  { value: "kn-IN", label: "Kannada" },
  { value: "ml-IN", label: "Malayalam" },
  { value: "pa-IN", label: "Punjabi" },
  { value: "ta-IN", label: "Tamil" },
  { value: "te-IN", label: "Telugu" },
];

export const TEMPLATE_LANGS: { value: TemplateLanguage; label: string }[] = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "mr", label: "Marathi" },
  { value: "hi-en", label: "Hinglish (Hindi and English mixed)" },
];

export function roleLabel(r: Role) {
  return ROLES.find((x) => x.value === r)?.label ?? r;
}
export function langLabel(c: string | undefined = "en") {
  return STT_LANGS.find((x) => x.value === c)?.label ?? TEMPLATE_LANGS.find((x) => x.value === c)?.label ?? c ?? "English";
}

function slug(name: string) {
  return (
    "p_" +
    name
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/[\s-]+/g, "_")
      .slice(0, 24)
  );
}

export function emptyParticipant(): ParticipantSpec {
  return {
    id: "",
    display_name: "",
    roles: ["student"],
    skill: "lay",
    location_id: "",
    languages: { stt_candidates: ["hi-IN"], template_language: "hi", codemix: false },
  };
}

export function ParticipantForm({
  initial,
  pack,
  existingIds,
  onSubmit,
  onCancel,
  submitLabel = "Save participant",
}: {
  initial?: ParticipantSpec;
  pack?: SitePack;
  existingIds: string[];
  onSubmit: (p: ParticipantSpec) => void;
  onCancel?: () => void;
  submitLabel?: string;
}) {
  const editing = Boolean(initial?.id);
  const [p, setP] = useState<ParticipantSpec>(initial ?? emptyParticipant());
  const [touched, setTouched] = useState(false);
  const [idEdited, setIdEdited] = useState(editing);

  const errors = {
    name: !p.display_name.trim() ? "Enter a name people will recognise." : null,
    id: !p.id
      ? "An ID is needed."
      : !/^[a-z0-9_]{2,40}$/.test(p.id)
        ? "Use lowercase letters, numbers and underscores."
        : !editing && existingIds.includes(p.id)
          ? "Someone already has this ID."
          : null,
    roles: p.roles.length === 0 ? "Choose at least one role." : null,
    location: !p.location_id ? "Choose where this person is right now." : null,
    langs:
      p.languages.stt_candidates.length === 0
        ? "Choose at least one language they speak."
        : p.languages.stt_candidates.length > 4
          ? "Choose at most four languages."
          : null,
  };
  const valid = Object.values(errors).every((e) => !e);
  const show = (e: string | null) => (touched ? e : null);

  const set = (patch: Partial<ParticipantSpec>) => setP((cur) => ({ ...cur, ...patch }));
  const setLang = (patch: Partial<ParticipantSpec["languages"]>) =>
    setP((cur) => ({ ...cur, languages: { ...cur.languages, ...patch } }));

  const floors = pack ? [...new Set(pack.locations.map((l) => l.floor))].sort() : [];

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (valid) onSubmit({ ...p, display_name: p.display_name.trim() });
      }}
      className="flex flex-col gap-5"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name" error={show(errors.name)}>
          {(a) => (
            <Input
              {...a}
              autoFocus
              value={p.display_name}
              onChange={(e) => {
                const name = e.target.value;
                set({ display_name: name, ...(idEdited ? {} : { id: slug(name) }) });
              }}
              placeholder="Riya"
            />
          )}
        </Field>
        <Field label="Participant ID" hint="Used in the API and in links." error={show(errors.id)}>
          {(a) => (
            <Input
              {...a}
              value={p.id}
              disabled={editing}
              onChange={(e) => {
                setIdEdited(true);
                set({ id: e.target.value });
              }}
              className="font-mono text-[14px]"
              placeholder="p_riya"
            />
          )}
        </Field>
      </div>

      <fieldset>
        <legend className="mb-2 text-[13px] font-medium text-fg-2">Roles</legend>
        <div className="flex flex-wrap gap-2">
          {ROLES.map((r) => {
            const on = p.roles.includes(r.value);
            return (
              <button
                key={r.value}
                type="button"
                aria-pressed={on}
                onClick={() => set({ roles: on ? p.roles.filter((x) => x !== r.value) : [...p.roles, r.value] })}
                className={clsx(
                  "h-[34px] rounded-full px-3 text-[13px] transition-colors",
                  on ? "bg-accent-soft text-accent shadow-[inset_0_0_0_0.8px_var(--accent-line)]" : "text-muted shadow-[inset_0_0_0_0.8px_var(--app-line)] hover:text-fg",
                )}
              >
                {r.label}
              </button>
            );
          })}
        </div>
        {show(errors.roles) ? <p className="mt-1.5 text-[12px] text-bad">{errors.roles}</p> : null}
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Skill" hint={SKILLS.find((s) => s.value === p.skill)?.hint}>
          {(a) => (
            <Select {...a} value={p.skill} onChange={(e) => set({ skill: e.target.value as Skill })}>
              {SKILLS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field
          label="Current location"
          error={show(errors.location)}
          hint={pack ? undefined : "Load the site model to choose from its rooms."}
        >
          {(a) =>
            pack ? (
              <Select {...a} value={p.location_id} onChange={(e) => set({ location_id: e.target.value })}>
                <option value="">Choose a place</option>
                {floors.map((f) => (
                  <optgroup key={f} label={`Floor ${f}`}>
                    {pack.locations
                      .filter((l) => l.floor === f)
                      .map((l) => (
                        <option key={l.id} value={l.id}>
                          {l.label.replace(/^the /, "")}
                          {l.restricted ? " (restricted)" : ""}
                        </option>
                      ))}
                  </optgroup>
                ))}
              </Select>
            ) : (
              <Input {...a} value={p.location_id} onChange={(e) => set({ location_id: e.target.value })} placeholder="F3_R304" className="font-mono text-[14px]" />
            )
          }
        </Field>
      </div>

      <fieldset className="rounded-[14px] border-[0.8px] border-line p-4">
        <legend className="px-1 text-[13px] font-medium text-fg-2">Languages</legend>
        <p className="mb-3 text-[13px] text-muted">Which languages should speech recognition listen for? Choose one to four.</p>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
          {STT_LANGS.map((l) => (
            <Checkbox
              key={l.value}
              label={l.label}
              checked={p.languages.stt_candidates.includes(l.value)}
              onChange={(v) =>
                setLang({
                  stt_candidates: v
                    ? [...p.languages.stt_candidates, l.value]
                    : p.languages.stt_candidates.filter((x) => x !== l.value),
                })
              }
            />
          ))}
        </div>
        {show(errors.langs) ? <p className="mt-2 text-[12px] text-bad">{errors.langs}</p> : null}
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Field label="Ask questions in">
            {(a) => (
              <Select
                {...a}
                value={p.languages.template_language}
                onChange={(e) => setLang({ template_language: e.target.value as TemplateLanguage })}
              >
                {TEMPLATE_LANGS.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <div className="flex items-end pb-1.5">
            <Switch
              label="Mixes languages"
              description="Expect answers that switch language mid-sentence."
              checked={!!p.languages.codemix}
              onChange={(v) => setLang({ codemix: v })}
            />
          </div>
        </div>
      </fieldset>

      <div className="flex justify-end gap-2">
        {onCancel ? <Button onClick={onCancel}>Cancel</Button> : null}
        <Button type="submit" variant="primary">
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
