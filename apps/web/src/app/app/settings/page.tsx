"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Badge, Button, Card, CardHeader, Dialog, Field, KeyValue, Notice, PageHeader, Select, Skeleton, Switch } from "@/components/ui";
import { useCoreHealth, useVoiceStatus } from "@/lib/data/hooks";
import { clearLocalData, prefs, previewMode, usePrefs, usePreviewMode } from "@/lib/store/local";
import { describeError } from "@/lib/api/http";

export default function SettingsPage() {
  const p = usePrefs();
  const health = useCoreHealth();
  const voice = useVoiceStatus();
  const preview = usePreviewMode();
  const router = useRouter();
  const [confirmClear, setConfirmClear] = useState(false);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Settings" subtitle="Preferences are stored in this browser." />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <CardHeader title="Connection" subtitle="The console reaches the core and simulator through this app's own server." />
          <dl className="mt-3 divide-y divide-line">
            <KeyValue
              k="Core"
              v={
                <Badge tone={health === "online" ? "ok" : health === "offline" ? "bad" : "muted"} dot>
                  {health === "online" ? "Connected" : health === "offline" ? "Unreachable" : "Checking"}
                </Badge>
              }
            />
            <KeyValue k="Core address" v={<span className="font-mono text-[12px]">{process.env.NEXT_PUBLIC_CORE_ADDRESS ?? "not set"} (PRAMANA_CORE_URL)</span>} />
            <KeyValue k="Simulator address" v={<span className="font-mono text-[12px]">PRAMANA_SIM_URL (default 127.0.0.1:8100)</span>} />
            <KeyValue
              k="Voice"
              v={
                voice.status === "loading" ? (
                  <Skeleton className="h-5 w-24" />
                ) : voice.status === "error" ? (
                  <span className="text-[13px] text-muted">{describeError(voice.error)}</span>
                ) : (
                  <Badge tone={voice.data.configured ? "ok" : "warn"}>{voice.data.configured ? `Configured · ${voice.data.stt_model ?? "STT"}` : "Not configured"}</Badge>
                )
              }
            />
          </dl>
          <div className="mt-4">
            <Field label="Refresh interval" hint="How often a running investigation checks for new events.">
              {(a) => (
                <Select {...a} value={String(p.pollMs)} onChange={(e) => prefs.set({ pollMs: Number(e.target.value) })}>
                  <option value="1000">Every second</option>
                  <option value="1500">Every 1.5 seconds</option>
                  <option value="3000">Every 3 seconds</option>
                  <option value="6000">Every 6 seconds</option>
                </Select>
              )}
            </Field>
          </div>
        </Card>

        <Card className="p-5">
          <CardHeader title="Accessibility and motion" />
          <div className="mt-4 flex flex-col gap-5">
            <Switch
              label="Reduce motion"
              description="Stops decorative animation and shortens transitions. Your system setting is always respected."
              checked={p.reduceMotion}
              onChange={(v) => prefs.set({ reduceMotion: v })}
            />
          </div>
        </Card>

        <Card className="p-5">
          <CardHeader title="Development preview" subtitle="Swaps every data source for clearly labelled sample data in this tab. It is not a sign-in." />
          <div className="mt-4 flex items-center justify-between gap-4">
            <Badge tone={preview ? "warn" : "muted"}>{preview ? "Preview is on" : "Preview is off"}</Badge>
            {preview ? (
              <Button onClick={() => previewMode.disable()}>Turn off preview</Button>
            ) : (
              <Button
                onClick={() => {
                  previewMode.enable();
                  router.push("/app");
                }}
              >
                Turn on preview
              </Button>
            )}
          </div>
        </Card>

        <Card className="p-5">
          <CardHeader title="Local data" subtitle="Display preferences kept in this browser. Investigations and participants live in the core." />
          <Notice className="mt-4">Clearing this does not delete anything in the core.</Notice>
          <Button variant="danger" className="mt-4" onClick={() => setConfirmClear(true)}>
            Clear local data
          </Button>
        </Card>
      </div>

      <Dialog
        open={confirmClear}
        onClose={() => setConfirmClear(false)}
        title="Clear local data?"
        description="Your display preferences will be reset in this browser. Nothing in the core changes."
        footer={
          <>
            <Button onClick={() => setConfirmClear(false)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => {
                clearLocalData();
                setConfirmClear(false);
              }}
            >
              Clear
            </Button>
          </>
        }
      />
    </div>
  );
}
