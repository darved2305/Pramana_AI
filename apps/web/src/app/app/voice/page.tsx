"use client";

import { useEffect, useState } from "react";
import { Badge, Card, CardHeader, ErrorState, KeyValue, Notice, PageHeader, ProbBar, Skeleton } from "@/components/ui";
import { core } from "@/lib/api/core";
import type { VoiceStatus, VoiceUsage } from "@/lib/api/types";

const REFRESH_MS = 5000;
const SERVICE_LABEL: Record<string, string> = { stt_rest: "Speech to text (Prisma)", stt_stream: "Live speech to text (Prisma)", tts: "Speech (Timbre)" };

/**
 * Which voice service the core calls and what it has spent today, against the governor's caps.
 * Spend and limits only: measured recognition accuracy and latency stay private (Gnani EULA).
 */
export default function VoicePage() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [usage, setUsage] = useState<VoiceUsage | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    const load = async () => {
      try {
        const [s, u] = await Promise.all([core.voiceStatus(ctrl.signal), core.voiceUsage(ctrl.signal)]);
        setStatus(s);
        setUsage(u);
        setError(null);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setError(e);
      }
    };
    void load();
    const t = setInterval(load, REFRESH_MS);
    return () => {
      clearInterval(t);
      ctrl.abort();
    };
  }, []);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Voice" subtitle="The speech service the core is using and today's spend, refreshed every 5 seconds." />
      {error && !usage ? (
        <Card>
          <ErrorState error={error} />
        </Card>
      ) : !status || !usage ? (
        <Skeleton className="h-[320px] rounded-[16px]" />
      ) : (
        <Meter status={status} usage={usage} />
      )}
    </div>
  );
}

function Meter({ status, usage }: { status: VoiceStatus; usage: VoiceUsage }) {
  const live = status.provider === "gnani";
  const budget = usage.limits.daily_budget_inr;
  const share = budget > 0 ? Math.min(1, usage.spent_today_inr / budget) : 0;
  const services = Object.entries(usage.by_service);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-5" aria-label="Provider">
        <CardHeader title="Provider" subtitle="Which speech service the core actually calls." />
        <dl className="mt-3 divide-y divide-line">
          <KeyValue
            k="Service"
            v={
              <Badge tone={!status.configured ? "muted" : live ? "ok" : "warn"} dot>
                {!status.configured ? "Voice off (no key)" : live ? "Live Gnani" : "Not Gnani (emulator?)"}
              </Badge>
            }
          />
          <KeyValue k="Host" v={<span className="font-mono text-[12px]">{status.provider_host ?? "unknown"}</span>} />
          <KeyValue k="Key" v={<Badge tone={status.configured ? "ok" : "warn"}>{status.configured ? "Configured on the server" : "Not configured"}</Badge>} />
          <KeyValue k="Models" v={<span className="text-[13px]">{[status.stt_model, ...(status.tts_models ?? [])].filter(Boolean).join(", ")}</span>} />
        </dl>
        {status.configured && !live ? (
          <Notice tone="warn" className="mt-4" title="Label runs as emulated">
            Voice on this core is not Gnani. Any rehearsal or recording made now must say so.
          </Notice>
        ) : null}
      </Card>

      <Card className="p-5" aria-label="Spend today">
        <CardHeader title="Spend today" subtitle="Priced before each call is sent and recorded after it, in UTC days." />
        <p className="mt-3 text-[28px] font-medium tabular-nums">
          Rs {usage.spent_today_inr.toFixed(2)} <span className="text-[15px] text-muted">of Rs {budget.toFixed(0)}</span>
        </p>
        <ProbBar value={share} tone={share >= 0.9 ? "bad" : share >= 0.6 ? "warn" : "ok"} label={`${Math.round(share * 100)}% of today's budget`} className="mt-2" />
        <p className="mt-1 text-[12px] text-muted">{Math.round(share * 100)}% of today&apos;s budget. Calls that would go over it are refused.</p>
        {services.length ? (
          <table className="mt-4 w-full text-[13px]">
            <thead className="text-muted">
              <tr>
                <th className="text-left font-normal">Service</th>
                <th className="text-right font-normal">Calls</th>
                <th className="text-right font-normal">Cost</th>
              </tr>
            </thead>
            <tbody>
              {services.map(([name, s]) => (
                <tr key={name} className="border-t border-line">
                  <td className="py-1.5">{SERVICE_LABEL[name] ?? name}</td>
                  <td className="py-1.5 text-right tabular-nums">{s.requests}</td>
                  <td className="py-1.5 text-right tabular-nums">Rs {s.cost_inr.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="mt-4 text-[13px] text-muted">No voice calls today.</p>
        )}
      </Card>

      <Card className="p-5 lg:col-span-2" aria-label="Limits now">
        <CardHeader title="Limits now" subtitle="The governor refuses work before it would exceed these, so nothing is sent that Gnani would reject." />
        <dl className="mt-3 grid gap-x-6 sm:grid-cols-3">
          <KeyValue k="Live speech sessions" v={<span className="tabular-nums">{usage.open_streams} of {usage.limits.max_streams}</span>} />
          <KeyValue k="Transcriptions this minute" v={<span className="tabular-nums">{usage.window_used.stt_rest} of {usage.limits.stt_rest_per_min}</span>} />
          <KeyValue k="Speech syntheses this minute" v={<span className="tabular-nums">{usage.window_used.tts} of {usage.limits.tts_per_min}</span>} />
        </dl>
      </Card>
    </div>
  );
}
