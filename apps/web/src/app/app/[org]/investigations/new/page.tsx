"use client";

import { Suspense, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, Notice, PageHeader, Select, Skeleton, Switch, Textarea } from "@/components/ui";
import { actionKey } from "@/lib/api/account";
import { describeError } from "@/lib/api/http";
import type { ParticipantSpec, SiteSummary } from "@/lib/api/types";
import { useLoad } from "@/lib/data/hooks";
import { useWorkspace } from "@/lib/org/context";

type Spec = {
  roles?: { id: string; label: string; skill: "lay" | "access" | "technician" }[] | null;
  locations: { id: string; label: { en: string }; restricted?: boolean; access_roles?: string[] }[];
  components: { id: string; label: string; failure_modes: { id: string; label: string }[] }[];
};

const BUILTIN = [
  { id: "student", label: "Student", skill: "lay" as const },
  { id: "guard", label: "Security guard", skill: "access" as const },
  { id: "electrician", label: "Electrician", skill: "technician" as const },
  { id: "it_tech", label: "IT technician", skill: "technician" as const },
];

/** One simulated person per role, generated from the site's own model (nothing hard-coded). */
function practiceCast(spec: Spec): ParticipantSpec[] {
  const open = spec.locations.filter((l) => !l.restricted);
  const hub = (open[0] ?? spec.locations[0]).id;
  return (spec.roles ?? BUILTIN).map((r, i) => ({
    id: `p_practice_${r.id}`.slice(0, 64),
    display_name: `${r.label} (simulated)`,
    roles: [r.id],
    skill: r.skill,
    location_id: r.skill === "lay" ? (open[i % Math.max(open.length, 1)]?.id ?? hub) : hub,
    languages: { stt_candidates: ["hi-IN", "en-IN"], template_language: "en" },
  }));
}

export default function NewWorkspaceInvestigation() {
  return (
    <Suspense>
      <NewInvestigation />
    </Suspense>
  );
}

function NewInvestigation() {
  const ws = useWorkspace();
  const router = useRouter();
  const params = useSearchParams();
  const sites = useLoad(`sites|${ws.org.id}`, (s) => ws.api.sites(s));
  const published = useMemo(() => (sites.status === "ready" ? sites.data.filter((s) => s.current_model_id) : []), [sites]);
  const wanted = params.get("site");
  const [siteId, setSiteId] = useState<string | null>(null);
  const site: SiteSummary | undefined =
    published.find((s) => s.id === siteId) ??
    published.find((s) => s.id === wanted) ??
    (params.get("practice") ? published.find((s) => s.mode === "sandbox") : undefined) ??
    published.find((s) => s.mode === "live") ??
    published[0];

  const model = useLoad(site ? `model|${site.current_model_id}` : null, (s) => ws.api.model(site!.id, site!.current_model_id as string, s));
  const people = useLoad(site ? `people|${site.id}` : null, (s) => ws.api.people(site!.id, s));
  const spec = model.status === "ready" ? (model.data.spec as unknown as Spec) : null;
  const listed = useMemo(() => (people.status === "ready" ? people.data.map((p) => p.person) : []), [people]);
  const cast = useMemo(() => (spec ? (listed.length ? listed : practiceCast(spec)) : []), [spec, listed]);

  const [report, setReport] = useState("");
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [reporter, setReporter] = useState<string | null>(null);
  const [affected, setAffected] = useState("");
  const [fault, setFault] = useState("random");
  const [parallel, setParallel] = useState(1);
  const [presence, setPresence] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [key] = useState(() => actionKey("investigation")); // one key per form: a retry never creates two

  const included = chosen ?? new Set(cast.map((p) => p.id));
  const members = cast.filter((p) => included.has(p.id));
  const reporterId = reporter && included.has(reporter) ? reporter : (members.find((p) => p.skill === "lay") ?? members[0])?.id;

  async function start() {
    if (!site || !spec || !reporterId || !report.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const [component_id, mode] = fault.split("|");
      const created = await ws.api.createInvestigation(
        {
          site_id: site.id,
          practice: site.mode === "live",
          participants: members,
          report: { text: report.trim(), reporter_id: reporterId, ...(affected ? { affected_location_id: affected } : {}) },
          scenario: {
            seed: Math.floor(Math.random() * 2 ** 31),
            fault: fault === "random" ? "random" : fault === "none" ? { faults: [] } : { faults: [{ component_id, mode }] },
          },
          max_parallel_calls: parallel,
          presence_checks: presence,
        },
        { key },
      );
      router.push(`${ws.base}/investigations/${created.id}`);
    } catch (e) {
      setError(describeError(e));
      setBusy(false);
    }
  }

  if (sites.status === "loading") return <Skeleton className="mt-6 h-64" />;
  if (sites.status === "error") return <ErrorState className="mt-6" error={sites.error} onRetry={sites.reload} />;
  if (!published.length) {
    return (
      <div className="pt-4">
        <Notice tone="warn" title="No published site yet">Describe and publish a site first. The practice site is published for you when the workspace is created.</Notice>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 pt-4">
      <PageHeader
        eyebrow={site ? <Badge tone={site.mode === "sandbox" ? "info" : "accent"}>{site.mode === "sandbox" ? "Practice site" : "Practice on your site"}</Badge> : null}
        title="Report a problem"
        subtitle="Pramana works out who to ask, what to ask them and when it knows enough. A hidden fault is sealed first, so you can check its reasoning at the end."
      />
      {site?.mode === "live" ? (
        <Notice tone="info" title="This is a practice run on your own model">
          The faults are simulated from your published model and the people are simulated where none are listed. Live investigations with real calls and messages are not set up yet.
        </Notice>
      ) : null}
      {error ? <Notice tone="bad" title="The investigation was not started">{error}</Notice> : null}

      <Card className="flex flex-col gap-5 p-5">
        <CardHeader title="Where and what" />
        <Field label="Site">
          {(a) => (
            <Select {...a} value={site?.id} onChange={(e) => { setSiteId(e.target.value); setChosen(null); setFault("random"); setAffected(""); }}>
              {published.map((s) => (
                <option key={s.id} value={s.id}>{s.name}{s.mode === "sandbox" ? " (practice)" : ""}</option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="What is wrong, in the reporter's words">
          {(a) => <Textarea {...a} rows={3} value={report} onChange={(e) => setReport(e.target.value)} placeholder="No water from the taps on the second floor since morning" />}
        </Field>
        {spec ? (
          <Field label="Where it was noticed" optional hint="Leave empty if the report does not say.">
            {(a) => (
              <Select {...a} value={affected} onChange={(e) => setAffected(e.target.value)}>
                <option value="">Not stated</option>
                {spec.locations.map((l) => <option key={l.id} value={l.id}>{l.label.en}</option>)}
              </Select>
            )}
          </Field>
        ) : null}
      </Card>

      <Card className="flex flex-col gap-4 p-5">
        <CardHeader
          title="Who can be asked"
          subtitle={listed.length ? "People listed for this site. Untick anyone who is not available." : "Nobody is listed for this site yet, so Pramana uses one simulated person per role."}
        />
        {model.status === "loading" || people.status === "loading" ? <Skeleton className="h-24" /> : null}
        {model.status === "error" ? <ErrorState error={model.error} onRetry={model.reload} /> : null}
        <ul className="grid gap-2 sm:grid-cols-2">
          {cast.map((p) => {
            const on = included.has(p.id);
            return (
              <li key={p.id} className="flex items-center gap-3 rounded-[12px] p-3 shadow-[inset_0_0_0_0.8px_var(--app-line)]">
                <input
                  type="checkbox"
                  aria-label={`Include ${p.display_name}`}
                  checked={on}
                  onChange={() => {
                    const next = new Set(included);
                    if (on) next.delete(p.id);
                    else next.add(p.id);
                    setChosen(next);
                  }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] text-fg">{p.display_name}</span>
                  <span className="block truncate text-[12px] text-muted">{p.roles.join(", ")} · {spec?.locations.find((l) => l.id === p.location_id)?.label.en ?? p.location_id}</span>
                </span>
                <label className="flex items-center gap-1.5 text-[12px] text-fg-2">
                  <input type="radio" name="reporter" disabled={!on} checked={reporterId === p.id} onChange={() => setReporter(p.id)} /> Reported it
                </label>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card className="flex flex-col gap-4 p-5">
        <CardHeader title="Practice settings" subtitle="The fault is sealed before anyone is asked; only the reveal shows it." />
        {spec ? (
          <Field label="Hidden fault">
            {(a) => (
              <Select {...a} value={fault} onChange={(e) => setFault(e.target.value)}>
                <option value="random">Chosen at random</option>
                <option value="none">Nothing is broken (a false alarm)</option>
                {spec.components.flatMap((c) =>
                  c.failure_modes.map((f) => (
                    <option key={`${c.id}|${f.id}`} value={`${c.id}|${f.id}`}>{f.label}</option>
                  )),
                )}
              </Select>
            )}
          </Field>
        ) : null}
        <Field label="People asked at the same time" hint="With more than one, a question in flight is withdrawn when another answer makes it pointless.">
          {(a) => <Input {...a} type="number" min={1} max={3} value={parallel} onChange={(e) => setParallel(Math.min(3, Math.max(1, Number(e.target.value) || 1)))} />}
        </Field>
        <Switch checked={presence} onChange={setPresence} label="Presence checks" description="Before relying on what someone says they saw in a restricted place, ask them to read a detail only someone there can see." />
      </Card>

      <div className="flex justify-end gap-2">
        <Button variant="primary" size="lg" onClick={start} disabled={busy || !report.trim() || !reporterId || !members.length}>
          {busy ? "Sealing the fault and starting..." : "Start investigation"}
        </Button>
      </div>
    </div>
  );
}
