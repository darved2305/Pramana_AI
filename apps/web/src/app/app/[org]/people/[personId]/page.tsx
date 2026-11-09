"use client";

import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Avatar } from "@/components/app/Avatar";
import { ConsentDialog, ConsentSummary } from "@/components/app/PersonPrivacy";
import { Button, ButtonLink, Card, ErrorState, Field, Input, Notice, PageHeader, Skeleton, Switch } from "@/components/ui";
import { actionKey } from "@/lib/api/account";
import { describeError } from "@/lib/api/http";
import type { QuietHours, SitePerson } from "@/lib/api/types";
import { useLoad } from "@/lib/data/hooks";
import { useWorkspace } from "@/lib/org/context";

export default function PersonPage() {
  const ws = useWorkspace();
  const { personId } = useParams<{ personId: string }>();
  const params = useSearchParams();
  const sites = useLoad(`sites|${ws.org.id}`, (signal) => ws.api.sites(signal));
  const remembered = ws.account.preferences.last_site_by_org?.[ws.org.id];
  const siteId = params.get("site") ?? (sites.status === "ready"
    ? (sites.data.find((site) => site.id === remembered) ?? sites.data.find((site) => site.mode === "live") ?? sites.data[0])?.id
    : undefined);
  const site = sites.status === "ready" ? sites.data.find((entry) => entry.id === siteId) : undefined;
  const people = useLoad(siteId ? `people|${ws.org.id}|${siteId}` : null, (signal) => ws.api.people(siteId as string, signal));
  const entry = people.status === "ready" ? people.data.find((person) => person.person.id === personId) : undefined;
  const consents = useLoad(siteId && entry ? `consents|${ws.org.id}|${siteId}|${personId}` : null, (signal) =>
    ws.api.consents(siteId as string, personId, signal),
  );
  const [consentOpen, setConsentOpen] = useState(false);

  if (sites.status === "loading" || people.status === "loading") {
    return <div className="flex flex-col gap-4 pt-4"><Skeleton className="h-12" /><Skeleton className="h-72" /></div>;
  }
  if (sites.status === "error") return <ErrorState error={sites.error} onRetry={sites.reload} />;
  if (people.status === "error") return <ErrorState error={people.error} onRetry={people.reload} />;
  if (!siteId || !site || !entry) {
    return (
      <div className="pt-4">
        <ButtonLink href={`${ws.base}/people`}>Back to people</ButtonLink>
        <Notice tone="warn" title="Person not found">Choose a person who is still listed at this site.</Notice>
      </div>
    );
  }

  const person = entry.person;
  const quietHours = entry.quiet_hours ?? { enabled: true, start: "22:00", end: "08:00", timezone: "Asia/Kolkata" };
  return (
    <div className="flex flex-col gap-5 pt-4">
      <ButtonLink href={`${ws.base}/people?site=${encodeURIComponent(siteId)}`}>Back to people</ButtonLink>
      <PageHeader
        title={person.display_name}
        subtitle={`${site.name} · ${person.roles.join(", ")} · ${person.languages.template_language}`}
        actions={ws.canOperate ? <Button onClick={() => setConsentOpen(true)}>Manage consent</Button> : undefined}
      />
      {consents.status === "error" ? <Notice tone="bad" title="Consent could not be loaded">Reload this page to try again.</Notice> : null}
      <Card className="flex flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <Avatar name={person.display_name} size={44} />
          <div>
            <h2 className="text-[16px] font-medium text-fg">Consent</h2>
            <p className="text-[13px] text-muted">Only current web consent lets a live investigation ask questions on the web.</p>
          </div>
        </div>
        <ConsentSummary
          records={consents.status === "ready" ? consents.data : undefined}
          failed={consents.status === "error"}
        />
        {!ws.canOperate ? <p className="text-[12px] text-muted">Ask an operator to send a consent request or update these records.</p> : null}
      </Card>
      {ws.canOperate ? (
        <PersonSettingsForm
          key={`${entry.person.id}-${entry.version}`}
          entry={entry}
          siteId={siteId}
          onSaved={people.reload}
        />
      ) : (
        <Card className="p-4">
          <h2 className="text-[16px] font-medium text-fg">Quiet hours</h2>
          <p className="mt-2 text-[14px] text-fg-2">
            {quietHours.enabled
              ? `${quietHours.start} to ${quietHours.end} (${quietHours.timezone})`
              : "No quiet-hours window is set."}
          </p>
        </Card>
      )}
      {consentOpen && consents.status === "ready" ? (
        <ConsentDialog
          person={person}
          siteId={siteId}
          api={ws.api}
          records={consents.data}
          onChanged={consents.reload}
          onClose={() => setConsentOpen(false)}
        />
      ) : null}
    </div>
  );
}

function PersonSettingsForm({
  entry,
  siteId,
  onSaved,
}: {
  entry: SitePerson;
  siteId: string;
  onSaved: () => void;
}) {
  const ws = useWorkspace();
  const [email, setEmail] = useState(entry.contact_email ?? "");
  const [quiet, setQuiet] = useState<QuietHours>(entry.quiet_hours ?? { enabled: true, start: "22:00", end: "08:00", timezone: "Asia/Kolkata" });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await ws.api.updatePerson(
        siteId,
        entry.person.id,
        { contact_email: email.trim() || null, quiet_hours: quiet },
        entry.version,
        { key: actionKey("person-settings") },
      );
      onSaved();
      setMessage("Contact and quiet-hours settings saved.");
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="card flex flex-col gap-5 p-4" onSubmit={(event) => void save(event)}>
      <div>
        <h2 className="text-[16px] font-medium text-fg">Contact and quiet hours</h2>
        <p className="mt-1 text-[13px] text-muted">Quiet hours use the person&apos;s local time. The default window is 10:00 pm to 8:00 am in Asia/Kolkata.</p>
      </div>
      {error ? <Notice tone="bad" title="Settings were not saved">{error}</Notice> : null}
      {message ? <Notice tone="ok" title="Saved">{message}</Notice> : null}
      <Field label="Email address" optional hint="Used only to email a consent link when Gmail is configured. No SMS or WhatsApp is sent.">
        {(props) => <Input {...props} type="email" autoComplete="email" maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" />}
      </Field>
      <Switch
        checked={quiet.enabled ?? true}
        onChange={(enabled) => setQuiet((current) => ({ ...current, enabled }))}
        label="Use quiet hours"
        description="The planner will not ask this person during this window."
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Quiet hours start">
          {(props) => <Input {...props} type="time" disabled={!quiet.enabled} value={quiet.start} onChange={(event) => setQuiet((current) => ({ ...current, start: event.target.value }))} />}
        </Field>
        <Field label="Quiet hours end">
          {(props) => <Input {...props} type="time" disabled={!quiet.enabled} value={quiet.end} onChange={(event) => setQuiet((current) => ({ ...current, end: event.target.value }))} />}
        </Field>
      </div>
      <Field label="Timezone" hint="Use an IANA timezone such as Asia/Kolkata or Asia/Dubai.">
        {(props) => <Input {...props} value={quiet.timezone} onChange={(event) => setQuiet((current) => ({ ...current, timezone: event.target.value }))} placeholder="Asia/Kolkata" />}
      </Field>
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={saving}>Save settings</Button>
      </div>
    </form>
  );
}
