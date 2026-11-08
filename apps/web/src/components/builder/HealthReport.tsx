"use client";

import { clsx } from "clsx";
import { Badge } from "@/components/ui";
import { IconAlert, IconCheck } from "@/components/ui/icons";
import type { ModelHealth } from "@/lib/api/types";
import { relative } from "@/lib/data/derive";

/** What the model health check found, in the order a site author should act on it. */
export function HealthReport({ health }: { health: ModelHealth }) {
  const errors = health.findings.filter((f) => f.severity === "error");
  const warnings = health.findings.filter((f) => f.severity === "warning");
  const simulated = health.faults.filter((f) => f.reportable && f.episodes > 0);
  const silent = health.faults.filter((f) => !f.reportable);
  return (
    <div className="flex flex-col gap-4">
      <div className={clsx("flex items-start gap-3 rounded-[12px] p-4", health.ok ? "bg-ok/10" : "bg-bad/10")}>
        <span className={clsx("mt-0.5", health.ok ? "text-ok" : "text-bad")} aria-hidden>
          {health.ok ? <IconCheck /> : <IconAlert />}
        </span>
        <div className="text-[14px]">
          <p className="font-medium text-fg">
            {health.ok ? "Ready to publish" : `${errors.length} problem${errors.length === 1 ? "" : "s"} to fix before publishing`}
          </p>
          <p className="mt-0.5 text-muted">
            Checked {relative(health.checked_at)} with{" "}
            {health.cast === "directory" ? `this site's ${health.people} people` : `one person per role (${health.people})`}.
            {health.cast === "one_per_role" ? " Add your real people for a truer check." : ""}
          </p>
        </div>
      </div>

      {errors.length || warnings.length ? (
        <ul className="flex flex-col gap-2" aria-label="Findings">
          {[...errors, ...warnings].map((f, i) => (
            <li key={`${f.code}-${i}`} className="flex items-start gap-2.5 text-[13px] leading-relaxed">
              <Badge tone={f.severity === "error" ? "bad" : "warn"}>{f.severity === "error" ? "Fix" : "Consider"}</Badge>
              <span className="text-fg-2">{f.message}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {simulated.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-[13px]">
            <caption className="mb-2 text-left text-[12px] text-muted">
              Simulated investigations per fault, with people who sometimes answer wrongly. Holding back is right when the people available cannot tell faults apart.
            </caption>
            <thead>
              <tr className="text-left text-[12px] uppercase tracking-[0.06em] text-muted">
                <th className="pb-2 pr-3 font-medium">Fault</th>
                <th className="pb-2 pr-3 font-medium">Outcome over {simulated[0].episodes} runs</th>
                <th className="pb-2 font-medium">Questions</th>
              </tr>
            </thead>
            <tbody>
              {simulated.map((f) => (
                <tr key={f.hypothesis} className="border-t border-white/[.06]">
                  <td className="py-2 pr-3 text-fg">{f.label}</td>
                  <td className="py-2 pr-3">
                    <OutcomeBar correct={f.correct} abstained={f.abstained} wrong={f.wrong} />
                  </td>
                  <td className="py-2 tabular-nums text-fg-2">{f.mean_questions != null ? f.mean_questions.toFixed(1) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {silent.length ? (
        <p className="text-[12px] leading-relaxed text-muted">
          Not simulated, because nobody listed would notice them where they are: {silent.map((f) => f.label).join("; ")}.
        </p>
      ) : null}
    </div>
  );
}

function OutcomeBar({ correct, abstained, wrong }: { correct: number; abstained: number; wrong: number }) {
  const total = correct + abstained + wrong || 1;
  const pct = (n: number) => `${(100 * n) / total}%`;
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-2 w-40 overflow-hidden rounded-full bg-white/[.06]" role="img" aria-label={`${correct} right, ${abstained} held back, ${wrong} wrong`}>
        <span className="bg-ok" style={{ width: pct(correct) }} />
        <span className="bg-warn" style={{ width: pct(abstained) }} />
        <span className="bg-bad" style={{ width: pct(wrong) }} />
      </div>
      <span className="whitespace-nowrap tabular-nums text-fg-2">
        {correct} right · {abstained} held back · {wrong} wrong
      </span>
    </div>
  );
}
