"use client";

import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { Badge, Button, Card, CardHeader, EmptyState, Notice, PageHeader, PreviewBadge } from "@/components/ui";
import { IconChart, IconUpload } from "@/components/ui/icons";
import { usePreviewMode } from "@/lib/store/local";

/** Shape written by eval/src/pramana_eval/runner.py `summarize()`. */
interface PolicySummary {
  n: number;
  failed_runs: number;
  success_rate: number | null;
  decision_accuracy: number | null;
  decided: number;
  accuracy_on_identifiable: number | null;
  false_confidence_rate: number | null;
  abstention_recall: number | null;
  abstention_precision: number | null;
  probes_mean: number | null;
  probes_median: number | null;
  effort_s_mean: number | null;
  people_mean: number | null;
  hit_step_limit: number;
}
interface Summary {
  git_sha?: string;
  seeds?: number[];
  scenario_mix?: Record<string, number>;
  policies: Record<string, PolicySummary>;
}

const METRICS: { key: keyof PolicySummary; label: string; kind: "rate" | "num"; better: "high" | "low"; help: string }[] = [
  { key: "success_rate", label: "Success", kind: "rate", better: "high", help: "Correct decision, or a justified abstention." },
  { key: "decision_accuracy", label: "Decision accuracy", kind: "rate", better: "high", help: "Correct among the episodes that decided." },
  { key: "false_confidence_rate", label: "False confidence", kind: "rate", better: "low", help: "Decided confidently and was wrong." },
  { key: "abstention_precision", label: "Abstention precision", kind: "rate", better: "high", help: "Abstentions that were warranted." },
  { key: "abstention_recall", label: "Abstention recall", kind: "rate", better: "high", help: "Warranted abstentions that happened." },
  { key: "probes_mean", label: "Questions asked", kind: "num", better: "low", help: "Mean questions per episode." },
  { key: "effort_s_mean", label: "People's time", kind: "num", better: "low", help: "Mean seconds of effort asked of people." },
  { key: "people_mean", label: "People involved", kind: "num", better: "low", help: "Mean distinct people asked." },
];

function parse(text: string): Summary {
  // Python's json writer emits NaN for undefined statistics; JSON.parse does not accept it.
  const v = JSON.parse(text.replace(/\bNaN\b/g, "null").replace(/-?\bInfinity\b/g, "null"));
  if (!v || typeof v !== "object" || typeof v.policies !== "object") throw new Error("This file has no policies section. Choose a summary.json from eval/reports.");
  return v as Summary;
}

export default function EvaluationPage() {
  const preview = usePreviewMode();
  const [loaded, setData] = useState<{ summary: Summary; name: string; sample: boolean } | null>(null);
  // Preview sample data never outlives preview mode.
  const data = loaded?.sample && !preview ? null : loaded;
  const [err, setErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!preview) return;
    import("@/lib/preview/fixtures").then((f) => setData({ summary: f.previewEvaluation as Summary, name: "preview sample", sample: true }));
  }, [preview]);

  const load = async (file: File) => {
    setErr(null);
    try {
      setData({ summary: parse(await file.text()), name: file.name, sample: false });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not read this file.");
    }
  };

  const policies = data ? Object.entries(data.summary.policies) : [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Evaluation"
        eyebrow={data?.sample ? <PreviewBadge /> : undefined}
        subtitle="Benchmark results from the evaluation harness. Results are only shown from a report you load; nothing is computed or estimated here."
        actions={
          <Button variant="primary" size="lg" onClick={() => input.current?.click()}>
            <IconUpload className="h-4 w-4" /> Load summary.json
          </Button>
        }
      />
      <input
        ref={input}
        type="file"
        accept="application/json,.json"
        className="sr-only"
        aria-label="Choose a summary.json report"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) load(f);
          e.target.value = "";
        }}
      />
      {err ? <Notice tone="bad" title="Could not load the report">{err}</Notice> : null}

      {!data ? (
        <Card
          className={clsx("border-dashed transition-colors", drag && "border-accent bg-accent-soft")}
          onDragOver={(e: React.DragEvent) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e: React.DragEvent) => {
            e.preventDefault();
            setDrag(false);
            const f = e.dataTransfer.files?.[0];
            if (f) load(f);
          }}
        >
          <EmptyState
            icon={<IconChart />}
            title="No report loaded"
            body={
              <>
                Run the benchmark, then drop its <code className="font-mono text-fg-2">eval/reports/&lt;run&gt;/summary.json</code> here. The core
                does not serve evaluation results yet.
              </>
            }
            action={<Button onClick={() => input.current?.click()}>Choose a file</Button>}
          />
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[13px]">
            <Badge tone="info">{data.name}</Badge>
            {data.summary.git_sha ? <Badge>commit {data.summary.git_sha}</Badge> : null}
            {data.summary.seeds ? <Badge>seeds {data.summary.seeds.join(" to ")}</Badge> : null}
            {data.summary.scenario_mix
              ? Object.entries(data.summary.scenario_mix).map(([k, v]) => (
                  <Badge key={k}>
                    {k.replace(/_/g, " ")}: {v}
                  </Badge>
                ))
              : null}
            {!data.sample ? (
              <button type="button" className="ml-auto text-accent hover:underline" onClick={() => setData(null)}>
                Clear
              </button>
            ) : null}
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {METRICS.slice(0, 4).map((m) => (
              <MetricCard key={m.key} m={m} policies={policies} />
            ))}
          </div>

          <Card className="overflow-hidden">
            <div className="p-4 pb-0">
              <CardHeader title="All metrics by policy" subtitle="Best value in each row is highlighted. n/a means the statistic was undefined for that run." />
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-[14px]">
                <thead className="border-y border-line text-[12px] uppercase tracking-[0.06em] text-muted">
                  <tr>
                    <th className="px-4 py-3 font-medium">Metric</th>
                    {policies.map(([name, p]) => (
                      <th key={name} className="px-4 py-3 font-medium">
                        {name}
                        <span className="block normal-case tracking-normal text-[11px]">
                          n={p.n}
                          {p.failed_runs ? `, ${p.failed_runs} failed` : ""}
                        </span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {METRICS.map((m) => {
                    const vals = policies.map(([, p]) => p[m.key] as number | null);
                    const real = vals.filter((v): v is number => v != null);
                    const best = real.length > 1 ? (m.better === "high" ? Math.max(...real) : Math.min(...real)) : null;
                    return (
                      <tr key={m.key}>
                        <td className="px-4 py-3">
                          <span className="block">{m.label}</span>
                          <span className="block text-[12px] text-muted">{m.help}</span>
                        </td>
                        {vals.map((v, k) => (
                          <td key={k} className={clsx("px-4 py-3 font-mono tabular-nums", v != null && v === best ? "text-accent" : v == null ? "text-muted" : "text-fg")}>
                            {fmt(v, m.kind)}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function fmt(v: number | null | undefined, kind: "rate" | "num") {
  if (v == null || Number.isNaN(v)) return "n/a";
  return kind === "rate" ? `${(v * 100).toFixed(1)}%` : v.toFixed(1);
}

function MetricCard({ m, policies }: { m: (typeof METRICS)[number]; policies: [string, PolicySummary][] }) {
  return (
    <Card className="p-4">
      <p className="text-[13px] text-muted">{m.label}</p>
      <ul className="mt-3 flex flex-col gap-2.5">
        {policies.map(([name, p]) => {
          const v = p[m.key] as number | null;
          return (
            <li key={name}>
              <div className="flex justify-between text-[13px]">
                <span className="truncate text-fg-2">{name}</span>
                <span className="font-mono">{fmt(v, m.kind)}</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/[.07]">
                <div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: v == null ? 0 : `${Math.min(1, v) * 100}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
