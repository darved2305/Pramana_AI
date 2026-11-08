"use client";

import { useState } from "react";
import { Button, Card, CardHeader, Notice } from "@/components/ui";
import { describeError } from "@/lib/api/http";
import type { InvestigationForecast, InvestigationState, MapDriftCheck } from "@/lib/api/types";
import { useInvestigationScope } from "@/lib/data/scope";

const pct = (x: number) => `${Math.round(x * 100)}%`;

const ADVICE: Record<InvestigationForecast["advice"], string> = {
  repair_in_progress: "A repair is being checked, so there is nothing to forecast.",
  ready_to_decide: "Pramana has enough evidence to decide now.",
  cannot_settle: "The people available cannot settle this. It needs someone else or another check.",
  keep_investigating: "Keep investigating: acting now would be a gamble, and more questions are likely to settle it.",
  could_act_now: "Acting now is reasonable. Further questions would add less.",
  keep_investigating_cautiously: "It is uncertain either way. More questions may not settle this.",
};

/** A forecast is advice only: it is computed on request and never changes the investigation. */
export function ForecastPanel({ state }: { state: InvestigationState }) {
  const scope = useInvestigationScope();
  const [forecast, setForecast] = useState<InvestigationForecast | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drift, setDrift] = useState<MapDriftCheck | null>(null);
  const [driftBusy, setDriftBusy] = useState(false);

  async function checkDrift() {
    setDriftBusy(true);
    setError(null);
    try {
      setDrift(await scope.mapDrift(state.id));
    } catch (e) {
      setError(describeError(e));
    } finally {
      setDriftBusy(false);
    }
  }

  const decisionLabel = (id: string | null) =>
    (id && state.belief.decisions.find((d) => d.id === id)?.label) || "no single decision";

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setForecast(await scope.forecast(state.id));
    } catch (e) {
      setError(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex flex-col gap-3 p-4" aria-label="Forecast">
      <CardHeader title="Forecast" subtitle="What is likely if this carries on. An estimate only: it does not affect the investigation." />
      {error ? <Notice tone="bad" title="The forecast did not work">{error}</Notice> : null}
      {forecast ? (
        <div className="flex flex-col gap-2 text-[13px] text-fg-2">
          <p className="font-medium text-fg">{ADVICE[forecast.advice]}</p>
          {forecast.rollouts > 0 ? (
            <>
              <p>
                About {forecast.expected_questions.toFixed(1)} more question{forecast.expected_questions.toFixed(1) === "1.0" ? "" : "s"}, roughly {forecast.expected_minutes.toFixed(1)} min of people&apos;s time.
              </p>
              <p>
                Over {forecast.rollouts} simulated runs: {pct(forecast.p_right_decision)} reached the right decision, {pct(forecast.p_wrong_decision)} a wrong one, {pct(forecast.p_no_decision)} no decision.
              </p>
            </>
          ) : null}
          <p>
            If you acted now on the leading decision ({decisionLabel(forecast.leading_decision)}), it would be wrong about {pct(forecast.p_wrong_if_acted_now)} of the time.
          </p>
          {forecast.p_outside_model > 0.05 ? <p>Chance the real cause is outside this site&apos;s model: {pct(forecast.p_outside_model)}.</p> : null}
        </div>
      ) : null}
      <div>
        <Button size="sm" disabled={busy} onClick={run}>
          {busy ? "Estimating..." : forecast ? "Estimate again" : "Estimate the rest of this investigation"}
        </Button>
      </div>
      <div className="flex flex-col gap-2 border-t border-white/[.06] pt-3 text-[13px] text-fg-2">
        {drift ? (
          drift.status === "not_enough_evidence" ? (
            <p>Not enough answers yet to judge whether the site&apos;s map is right.</p>
          ) : drift.status === "repair_in_progress" ? (
            <p>A repair is being checked, so the map is not being reviewed.</p>
          ) : drift.findings.length === 0 ? (
            <p>Checked {drift.variants_checked} possible map mistakes. The answers fit the documented map.</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {drift.findings.map((f) => (
                <li key={`${f.component}-${f.proposed}`}>
                  <span className="font-medium text-fg">Worth checking the documentation: </span>
                  the answers fit one fault ({f.best_fault_label}) if {f.component_label} is actually connected to {f.proposed_label}, not {f.documented_label} as documented ({pct(f.probability)}, an estimate).
                </li>
              ))}
            </ul>
          )
        ) : null}
        <div>
          <Button size="sm" variant="ghost" disabled={driftBusy} onClick={checkDrift}>
            {driftBusy ? "Checking..." : "Check whether the site's map fits"}
          </Button>
        </div>
      </div>
    </Card>
  );
}
