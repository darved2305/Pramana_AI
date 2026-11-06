"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { clsx } from "clsx";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Notice,
  PageHeader,
  PreviewBadge,
  Select,
  Skeleton,
  Switch,
  Textarea,
} from "@/components/ui";
import { IconArrowLeft, IconArrowRight, IconCheck, IconPlus, IconUsers } from "@/components/ui/icons";
import { BuildingMap } from "@/components/app/BuildingMap";
import { Avatar } from "@/components/app/Avatar";
import { ParticipantForm, TEMPLATE_LANGS, langLabel, roleLabel } from "@/components/app/ParticipantForm";
import { useDirectory, usePack, usePacks } from "@/lib/data/hooks";
import { core, DEFAULT_PACK, type InvestigationPreset } from "@/lib/api/core";
import { describeError } from "@/lib/api/http";
import { usePreviewMode } from "@/lib/store/local";
import type { CreateInvestigation, ParticipantSpec, TemplateLanguage } from "@/lib/api/types";

const STEPS = ["Site", "Problem", "Participants", "Languages", "Permissions", "Configuration", "Confirm"] as const;
type Step = (typeof STEPS)[number];

export default function NewInvestigationPage() {
  const router = useRouter();
  const preview = usePreviewMode();
  const [step, setStep] = useState(0);
  const [packId, setPackId] = useState<string>(DEFAULT_PACK);
  const pack = usePack(packId);
  const packs = usePacks();
  const directory = useDirectory(packId);
  const people = useMemo(() => directory.data?.map((d) => d.participant) ?? [], [directory.data]);
  const [report, setReport] = useState("");
  const [affected, setAffected] = useState<string>("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [reporter, setReporter] = useState<string>("");
  const [overrides, setOverrides] = useState<Record<string, Partial<ParticipantSpec>>>({});
  const [seed, setSeed] = useState("19");
  const [parallel, setParallel] = useState(1);
  const [faultMode, setFaultMode] = useState<"random" | "specified">("random");
  const [faultComponent, setFaultComponent] = useState("");
  const [faultKind, setFaultKind] = useState("");
  const [ack, setAck] = useState(false);
  const [touched, setTouched] = useState<Record<number, boolean>>({});
  const [adding, setAdding] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [presets, setPresets] = useState<InvestigationPreset[]>([]);
  const [presetError, setPresetError] = useState<unknown>(null);
  const [startingPreset, setStartingPreset] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    core.investigationPresets(controller.signal).then(setPresets).catch((error: unknown) => {
      if (!controller.signal.aborted) setPresetError(error);
    });
    return () => controller.abort();
  }, []);

  const participants: ParticipantSpec[] = useMemo(
    () =>
      people
        .filter((p) => chosen.includes(p.id))
        .map((p) => ({
          ...p,
          ...overrides[p.id],
          languages: { ...p.languages, ...(overrides[p.id]?.languages ?? {}) },
        })),
    [people, chosen, overrides],
  );

  const errors: Record<number, string | null> = {
    0: pack.status !== "ready" ? "The site model has to load before you continue." : null,
    1: report.trim().length < 6 ? "Describe the problem in a few words, the way the reporter said it." : null,
    2: chosen.length === 0 ? "Choose at least one participant." : !reporter || !chosen.includes(reporter) ? "Choose who reported the problem." : null,
    3: null,
    4: participants.every((p) => p.available === false) ? "At least one participant must be available to answer." : null,
    5:
      !/^\d{1,9}$/.test(seed)
        ? "The seed is a whole number."
        : faultMode === "specified" && (!/^[A-Z0-9_]+$/.test(faultComponent) || !/^[a-z_]+$/.test(faultKind))
          ? "Give a component ID like CB_C2_7 and a mode like tripped."
          : null,
    6: !ack ? "Confirm that the people listed have agreed to be contacted." : null,
  };

  const go = (n: number) => {
    if (n > step) {
      setTouched((t) => ({ ...t, [step]: true }));
      if (errors[step]) return;
    }
    setStep(n);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const body: CreateInvestigation | null =
    pack.status === "ready"
      ? {
          pack_id: packId,
          participants,
          report: { text: report.trim(), reporter_id: reporter, affected_location_id: affected || null },
          scenario: {
            seed: Number(seed),
            fault: faultMode === "random" ? "random" : { faults: [{ component_id: faultComponent, mode: faultKind }] },
          },
          max_parallel_calls: parallel,
        }
      : null;

  const submit = async () => {
    setTouched((t) => ({ ...t, 6: true }));
    if (Object.values(errors).some(Boolean) || !body || preview) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const s = await core.createInvestigation(body);
      router.push(`/app/investigations/${s.id}`);
    } catch (e) {
      setSubmitError(e);
      setSubmitting(false);
    }
  };

  const startPreset = async (preset: InvestigationPreset) => {
    if (preview) return;
    setStartingPreset(preset.id);
    setPresetError(null);
    try {
      const investigation = await core.createInvestigation(preset.request);
      router.push(`/app/investigations/${investigation.id}`);
    } catch (error) {
      setPresetError(error);
      setStartingPreset(null);
    }
  };

  const err = touched[step] ? errors[step] : null;
  const current: Step = STEPS[step];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="New investigation"
        eyebrow={preview ? <PreviewBadge /> : undefined}
        subtitle="Tell Pramana what is wrong and who can help. It will decide whom to ask, and what, one question at a time."
      />

      {presets.length > 0 ? (
        <Card className="p-4 sm:p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="max-w-xl">
              <h2 className="font-serif text-[22px] tracking-[0.02em]">Try a scenario</h2>
              <p className="mt-1 text-[13px] text-muted">
                Simulated scenarios: start S2 to follow a Wi-Fi reconciliation, or S7 to test a restricted-location check.
                Both use fictional participants and a sealed simulated fault.
              </p>
              {presetError ? (
                <p className="mt-2 text-[13px] text-bad" role="alert">{describeError(presetError)}</p>
              ) : null}
            </div>
            <div className="grid w-full gap-2 sm:max-w-[360px] sm:grid-cols-2">
              {presets.map((preset) => (
                <Button
                  key={preset.id}
                  variant="secondary"
                  onClick={() => startPreset(preset)}
                  loading={startingPreset === preset.id}
                  disabled={preview || startingPreset !== null}
                  aria-label={`Start ${preset.id}: ${preset.title}`}
                >
                  Start {preset.id}
                </Button>
              ))}
            </div>
          </div>
        </Card>
      ) : null}

      <nav aria-label="Steps" className="overflow-x-auto pb-1 [scrollbar-width:none]">
        <ol className="flex min-w-max items-center gap-1">
          {STEPS.map((s, i) => (
            <li key={s} className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => (i < step ? go(i) : i === step + 1 ? go(i) : undefined)}
                disabled={i > step + 1}
                aria-current={i === step ? "step" : undefined}
                className={clsx(
                  "flex h-9 items-center gap-2 rounded-full px-3 text-[13px] font-medium transition-colors",
                  i === step ? "bg-accent-soft text-accent" : i < step ? "text-fg hover:bg-white/[.05]" : "text-muted",
                )}
              >
                <span
                  className={clsx(
                    "grid h-5 w-5 place-items-center rounded-full text-[11px]",
                    i < step ? "bg-accent text-accent-ink" : i === step ? "border border-accent" : "border border-line-strong",
                  )}
                >
                  {i < step ? <IconCheck className="h-3 w-3" /> : i + 1}
                </span>
                {s}
              </button>
              {i < STEPS.length - 1 ? <span className="h-px w-4 bg-line" aria-hidden /> : null}
            </li>
          ))}
        </ol>
      </nav>

      <Card className="p-5 sm:p-6">
        <h2 className="font-serif text-[28px] tracking-[0.02em]">{stepTitle(current)}</h2>
        <p className="mt-1 text-[14px] text-muted">{stepHelp(current)}</p>

        <div className="mt-6">
          {current === "Site" ? (
            pack.status === "loading" ? (
              <Skeleton className="h-[280px]" />
            ) : pack.status === "error" ? (
              <ErrorState error={pack.error} />
            ) : (
              <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
                <div className="flex flex-col gap-4">
                  <Field label="Site model">
                    {(a) => (
                      <Select {...a} value={packId} onChange={(e) => setPackId(e.target.value)}>
                        {(packs.data ?? [{ id: packId, title: packId }]).map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.title} ({p.id})
                          </option>
                        ))}
                      </Select>
                    )}
                  </Field>
                  <div className="rounded-[12px] bg-white/[.03] p-4 text-[14px]">
                    <p className="font-medium">{pack.data.title}</p>
                    <p className="mt-1 text-muted">
                      {new Set(pack.data.locations.map((l) => l.floor)).size} floors, {pack.data.locations.length} places,{" "}
                      {pack.data.probes.length} kinds of check.
                    </p>
                  </div>
                </div>
                <BuildingMap pack={pack.data} compact />
              </div>
            )
          ) : null}

          {current === "Problem" ? (
            <div className="grid gap-5 lg:grid-cols-[1fr_1fr]">
              <div className="flex flex-col gap-4">
                <Field
                  label="What is wrong?"
                  hint="Use the reporter's own words, in any language. For example: Floor 3 pe WiFi nahi chal raha."
                  error={err}
                >
                  {(a) => (
                    <Textarea {...a} autoFocus value={report} onChange={(e) => setReport(e.target.value)} placeholder="Describe the problem" maxLength={500} />
                  )}
                </Field>
                <Field label="Where is it noticed?" optional hint="Click a place on the plan, or leave it for Pramana to find out.">
                  {(a) => (
                    <Select {...a} value={affected} onChange={(e) => setAffected(e.target.value)}>
                      <option value="">Not sure</option>
                      {pack.data?.locations.map((l) => (
                        <option key={l.id} value={l.id}>
                          Floor {l.floor}: {l.label.replace(/^the /, "")}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              </div>
              {pack.data ? (
                <BuildingMap pack={pack.data} compact selected={affected} onSelect={(id) => setAffected((a) => (a === id ? "" : id))} overlay={{ affectedId: affected }} />
              ) : null}
            </div>
          ) : null}

          {current === "Participants" ? (
            people.length === 0 ? (
              <EmptyState
                icon={<IconUsers />}
                title="No participants yet"
                body="Add the people who can answer questions on site. They are saved to the site directory for next time."
                action={
                  <Button variant="primary" onClick={() => setAdding(true)}>
                    <IconPlus className="h-4 w-4" /> Add participant
                  </Button>
                }
              />
            ) : (
              <div className="flex flex-col gap-4">
                <ul className="grid gap-2 md:grid-cols-2">
                  {people.map((p) => {
                    const on = chosen.includes(p.id);
                    return (
                      <li key={p.id}>
                        <div
                          className={clsx(
                            "flex items-center gap-3 rounded-[12px] border-[0.8px] p-3 transition-colors",
                            on ? "border-accent/60 bg-accent-soft" : "border-line",
                          )}
                        >
                          <Checkbox
                            checked={on}
                            onChange={(v) => {
                              setChosen((c) => (v ? [...c, p.id] : c.filter((x) => x !== p.id)));
                              if (!v && reporter === p.id) setReporter("");
                            }}
                            label={
                              <span className="flex items-center gap-2.5">
                                <Avatar name={p.display_name} size={30} />
                                <span>
                                  <span className="block text-[14px] font-medium">{p.display_name}</span>
                                  <span className="block text-[12px] text-muted">
                                    {p.roles.map(roleLabel).join(", ")} · {pack.data?.locations.find((l) => l.id === p.location_id)?.label ?? p.location_id}
                                  </span>
                                </span>
                              </span>
                            }
                          />
                          {on ? (
                            <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-[12px] text-fg-2">
                              <input
                                type="radio"
                                name="reporter"
                                checked={reporter === p.id}
                                onChange={() => setReporter(p.id)}
                                className="accent-[var(--accent)]"
                              />
                              Reported it
                            </label>
                          ) : null}
                        </div>
                      </li>
                    );
                  })}
                </ul>
                {err ? <p className="text-[13px] text-bad" role="alert">{err}</p> : null}
                <div>
                  <Button onClick={() => setAdding(true)} disabled={preview}>
                    <IconPlus className="h-4 w-4" /> Add someone new
                  </Button>
                </div>
              </div>
            )
          ) : null}

          {current === "Languages" ? (
            <ul className="flex flex-col gap-3">
              {participants.map((p) => (
                <li key={p.id} className="grid items-center gap-3 rounded-[12px] border-[0.8px] border-line p-3 md:grid-cols-[1fr_260px_200px]">
                  <div className="flex items-center gap-3">
                    <Avatar name={p.display_name} size={32} />
                    <div>
                      <p className="text-[14px] font-medium">{p.display_name}</p>
                      <p className="text-[12px] text-muted">Listens for {p.languages.stt_candidates.map(langLabel).join(", ")}</p>
                    </div>
                  </div>
                  <Field label="Ask in">
                    {(a) => (
                      <Select
                        {...a}
                        value={p.languages.template_language}
                        onChange={(e) =>
                          setOverrides((o) => ({
                            ...o,
                            [p.id]: { ...o[p.id], languages: { ...p.languages, template_language: e.target.value as TemplateLanguage } },
                          }))
                        }
                      >
                        {TEMPLATE_LANGS.map((l) => (
                          <option key={l.value} value={l.value}>
                            {l.label}
                          </option>
                        ))}
                      </Select>
                    )}
                  </Field>
                  <Switch
                    label="Mixed languages"
                    checked={!!p.languages.codemix}
                    onChange={(v) =>
                      setOverrides((o) => ({ ...o, [p.id]: { ...o[p.id], languages: { ...p.languages, codemix: v } } }))
                    }
                  />
                </li>
              ))}
            </ul>
          ) : null}

          {current === "Permissions" ? (
            <div className="flex flex-col gap-4">
              <ul className="flex flex-col gap-3">
                {participants.map((p) => (
                  <li key={p.id} className="grid items-center gap-3 rounded-[12px] border-[0.8px] border-line p-3 md:grid-cols-[1fr_220px_200px]">
                    <div className="flex items-center gap-3">
                      <Avatar name={p.display_name} size={32} />
                      <div>
                        <p className="text-[14px] font-medium">{p.display_name}</p>
                        <p className="text-[12px] text-muted">
                          Can enter:{" "}
                          {pack.data?.locations
                            .filter((l) => l.restricted && l.access_roles.some((r) => p.roles.includes(r)))
                            .map((l) => l.label.replace(/^the /, ""))
                            .join(", ") || "open areas only"}
                        </p>
                      </div>
                    </div>
                    <Switch
                      label="Available now"
                      checked={p.available !== false}
                      onChange={(v) => setOverrides((o) => ({ ...o, [p.id]: { ...o[p.id], available: v } }))}
                    />
                    <Field label="Question limit" optional>
                      {(a) => (
                        <Input
                          {...a}
                          type="number"
                          min={1}
                          max={50}
                          inputMode="numeric"
                          value={p.question_budget ?? ""}
                          placeholder="No limit"
                          onChange={(e) =>
                            setOverrides((o) => ({
                              ...o,
                              [p.id]: { ...o[p.id], question_budget: e.target.value ? Math.max(1, Number(e.target.value)) : undefined },
                            }))
                          }
                        />
                      )}
                    </Field>
                  </li>
                ))}
              </ul>
              {err ? <p className="text-[13px] text-bad" role="alert">{err}</p> : null}
              <Notice tone="info" title="Repairs always need approval">
                Pramana never acts on equipment by itself. Any repair it proposes waits for a person to approve it, and
                the capability it issues expires after five minutes.
              </Notice>
            </div>
          ) : null}

          {current === "Configuration" ? (
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="flex flex-col gap-4">
                <Field label="Simulation seed" hint="The same seed and fault reproduce the same run." error={err && err.includes("seed") ? err : null}>
                  {(a) => <Input {...a} inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} className="font-mono" />}
                </Field>
                <Field label="People asked at once" hint="With more than one, a question still out is withdrawn when another answer makes it pointless. At most 3.">
                  {(a) => (
                    <Select {...a} value={String(parallel)} onChange={(e) => setParallel(Number(e.target.value))} data-testid="parallel-calls">
                      <option value="1">One at a time</option>
                      <option value="2">Up to 2</option>
                      <option value="3">Up to 3</option>
                    </Select>
                  )}
                </Field>
                <fieldset className="flex flex-col gap-3">
                  <legend className="mb-1 text-[13px] font-medium text-fg-2">Hidden fault</legend>
                  <label className="flex cursor-pointer items-start gap-3 rounded-[12px] border-[0.8px] border-line p-3 has-[:checked]:border-accent/60">
                    <input type="radio" name="fault" checked={faultMode === "random"} onChange={() => setFaultMode("random")} className="mt-1 accent-[var(--accent)]" />
                    <span>
                      <span className="block text-[14px] font-medium">Sealed and random</span>
                      <span className="block text-[13px] text-muted">The simulator picks the fault. Only its hash is shown until the reveal.</span>
                    </span>
                  </label>
                  <label className="flex cursor-pointer items-start gap-3 rounded-[12px] border-[0.8px] border-line p-3 has-[:checked]:border-accent/60">
                    <input type="radio" name="fault" checked={faultMode === "specified"} onChange={() => setFaultMode("specified")} className="mt-1 accent-[var(--accent)]" />
                    <span>
                      <span className="block text-[14px] font-medium">Specified</span>
                      <span className="block text-[13px] text-muted">For demonstrations: choose the component and failure mode.</span>
                    </span>
                  </label>
                </fieldset>
              </div>
              {faultMode === "specified" ? (
                <div className="flex flex-col gap-4">
                  <Field label="Component ID" hint="For example CB_C2_7 or AP_3A.">
                    {(a) => <Input {...a} value={faultComponent} onChange={(e) => setFaultComponent(e.target.value.toUpperCase())} className="font-mono" />}
                  </Field>
                  <Field label="Failure mode" hint="For example tripped, dead, down or lost.">
                    {(a) => <Input {...a} value={faultKind} onChange={(e) => setFaultKind(e.target.value.toLowerCase())} className="font-mono" />}
                  </Field>
                  {err && !err.includes("seed") ? <p className="text-[13px] text-bad" role="alert">{err}</p> : null}
                </div>
              ) : (
                <Notice>
                  The core never stores the fault. It publishes a SHA-256 commitment when the investigation opens, so the
                  diagnosis can be checked against it afterwards.
                </Notice>
              )}
            </div>
          ) : null}

          {current === "Confirm" ? (
            <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
              <dl className="grid gap-3 text-[14px]">
                <Summary k="Site" v={pack.data?.title ?? packId} onEdit={() => go(0)} />
                <Summary k="Problem" v={<>&ldquo;{report.trim()}&rdquo;{affected ? <span className="text-muted"> at {pack.data?.locations.find((l) => l.id === affected)?.label}</span> : null}</>} onEdit={() => go(1)} />
                <Summary
                  k="Participants"
                  v={
                    <span className="flex flex-wrap gap-1.5">
                      {participants.map((p) => (
                        <Badge key={p.id} tone={p.id === reporter ? "accent" : "muted"}>
                          {p.display_name}
                          {p.id === reporter ? " (reporter)" : ""}
                          {p.available === false ? " (away)" : ""}
                        </Badge>
                      ))}
                    </span>
                  }
                  onEdit={() => go(2)}
                />
                <Summary k="Languages" v={participants.map((p) => `${p.display_name}: ${langLabel(p.languages.template_language)}`).join(" · ")} onEdit={() => go(3)} />
                <Summary k="Scenario" v={`Seed ${seed} · ${faultMode === "random" ? "sealed random fault" : `${faultComponent} ${faultKind}`} · ${parallel === 1 ? "one person at a time" : `up to ${parallel} people at once`}`} onEdit={() => go(5)} />
              </dl>
              <div className="flex flex-col gap-4">
                <Checkbox
                  checked={ack}
                  onChange={setAck}
                  label="These people have agreed to be contacted"
                  description="Pramana will message them and may ask them to walk to a place and look at something."
                />
                {err ? <p className="text-[13px] text-bad" role="alert">{err}</p> : null}
                {submitError ? (
                  <Notice tone="bad" title="Could not create the investigation">
                    {describeError(submitError)}
                  </Notice>
                ) : null}
                {preview ? (
                  <Notice tone="warn" title="Disabled in preview">
                    Creating an investigation needs the core. Exit preview to start a real one, or open the{" "}
                    <Link href="/app/investigations/preview-0001" className="underline">
                      preview investigation
                    </Link>
                    .
                  </Notice>
                ) : null}
                <Button variant="primary" size="lg" onClick={submit} loading={submitting} disabled={preview}>
                  Start investigation
                </Button>
              </div>
            </div>
          ) : null}
        </div>

        {err && !["Problem", "Participants", "Permissions", "Configuration", "Confirm"].includes(current) ? (
          <p className="mt-4 text-[13px] text-bad" role="alert">
            {err}
          </p>
        ) : null}

        <div className="mt-8 flex items-center justify-between border-t border-line pt-5">
          <Button onClick={() => go(step - 1)} disabled={step === 0}>
            <IconArrowLeft className="h-4 w-4" /> Back
          </Button>
          {step < STEPS.length - 1 ? (
            <Button variant="primary" onClick={() => go(step + 1)}>
              Continue <IconArrowRight className="h-4 w-4" />
            </Button>
          ) : null}
        </div>
      </Card>

      <Dialog wide open={adding} onClose={() => setAdding(false)} title="Add participant" description="Saved to the site directory, so everyone on this site can call on them.">
        {adding ? (
          <ParticipantForm
            pack={pack.data}
            existingIds={people.map((p) => p.id)}
            onCancel={() => setAdding(false)}
            onSubmit={async (p) => {
              if (preview) throw new Error("The preview does not save participants.");
              await core.addParticipant(packId, p);
              directory.reload();
              setChosen((c) => [...c, p.id]);
              setAdding(false);
            }}
            submitLabel="Add and select"
          />
        ) : null}
      </Dialog>
    </div>
  );
}

function Summary({ k, v, onEdit }: { k: string; v: React.ReactNode; onEdit: () => void }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-[12px] bg-white/[.03] px-4 py-3">
      <div>
        <dt className="text-[12px] uppercase tracking-[0.06em] text-muted">{k}</dt>
        <dd className="mt-1 text-fg">{v}</dd>
      </div>
      <button type="button" onClick={onEdit} className="shrink-0 text-[13px] text-accent hover:underline">
        Edit
      </button>
    </div>
  );
}

function stepTitle(s: Step) {
  return {
    Site: "Which building?",
    Problem: "What is wrong?",
    Participants: "Who can help?",
    Languages: "How should Pramana speak to them?",
    Permissions: "Who is available, and how much can we ask?",
    Configuration: "Simulation settings",
    Confirm: "Ready to start",
  }[s];
}
function stepHelp(s: Step) {
  return {
    Site: "Pramana reasons over a model of the site: its floors, rooms, closets and the checks that can be made in each.",
    Problem: "A short description is enough. Pramana will turn it into competing explanations and test them.",
    Participants: "Choose the people on site. Pick everyone who could look at something; Pramana decides whom to ask.",
    Languages: "Questions are written and spoken in each person's language.",
    Permissions: "Mark anyone who cannot be reached now, and optionally cap how many questions each person gets.",
    Configuration: "This build runs against the simulator, which holds the hidden fault.",
    Confirm: "Check the details. You can still go back and change anything.",
  }[s];
}
