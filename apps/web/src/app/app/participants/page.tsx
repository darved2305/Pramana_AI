"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  Notice,
  PageHeader,
  PreviewBadge,
  Tabs,
  Tag,
} from "@/components/ui";
import { IconEdit, IconPlus, IconSearch, IconTrash, IconUsers } from "@/components/ui/icons";
import { ParticipantForm, ROLES, langLabel, roleLabel } from "@/components/app/ParticipantForm";
import { roster, usePreviewMode, useRoster } from "@/lib/store/local";
import { Avatar } from "@/components/app/Avatar";
import { usePack } from "@/lib/data/hooks";
import { locationLabel } from "@/lib/data/derive";
import type { ParticipantSpec, Role } from "@/lib/api/types";

export default function ParticipantsPage() {
  const preview = usePreviewMode();
  const stored = useRoster();
  const pack = usePack("campus_block_c");
  const [fixtures, setFixtures] = useState<ParticipantSpec[]>([]);
  const [role, setRole] = useState<Role | "all">("all");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<ParticipantSpec | "new" | null>(null);
  const [removing, setRemoving] = useState<ParticipantSpec | null>(null);

  useEffect(() => {
    if (!preview) return;
    import("@/lib/preview/fixtures").then((f) => setFixtures(f.previewParticipants));
  }, [preview]);

  const people = preview ? fixtures : stored;
  const shown = useMemo(
    () =>
      people.filter(
        (p) =>
          (role === "all" || p.roles.includes(role)) &&
          (!q.trim() || `${p.display_name} ${p.id}`.toLowerCase().includes(q.trim().toLowerCase())),
      ),
    [people, role, q],
  );

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Participants"
        eyebrow={preview ? <PreviewBadge /> : undefined}
        subtitle="The people Pramana can ask. Each has roles that decide what they can check, a place they are now, and the languages they speak."
        actions={
          <Button variant="primary" size="lg" onClick={() => setEditing("new")} disabled={preview} title={preview ? "Disabled in preview" : undefined}>
            <IconPlus className="h-4 w-4" /> Add participant
          </Button>
        }
      />

      {!preview ? (
        <Notice>
          The core has no participant directory yet. This roster is kept in this browser and is sent with each new
          investigation.
        </Notice>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs<Role | "all">
          label="Filter by role"
          value={role}
          onChange={setRole}
          items={[
            { value: "all", label: "All", count: people.length },
            ...ROLES.map((r) => ({ value: r.value, label: r.label.split(" ")[0], count: people.filter((p) => p.roles.includes(r.value)).length })),
          ]}
        />
        <div className="flex h-[38px] w-full max-w-[260px] items-center gap-2 rounded-full border-[0.8px] border-line px-3.5 focus-within:border-accent/60">
          <IconSearch className="h-4 w-4 text-muted" />
          <label htmlFor="people-filter" className="sr-only">
            Search participants
          </label>
          <input
            id="people-filter"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name or ID"
            className="w-full bg-transparent text-[14px] outline-none placeholder:text-muted"
          />
        </div>
      </div>

      {people.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconUsers />}
            title="Your roster is empty"
            body="Add the people on site who can answer questions: residents, guards, electricians and IT staff."
            action={
              <Button variant="primary" onClick={() => setEditing("new")}>
                <IconPlus className="h-4 w-4" /> Add the first participant
              </Button>
            }
          />
        </Card>
      ) : shown.length === 0 ? (
        <Card>
          <EmptyState title="No one matches" body="Try another role or clear the search." />
        </Card>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((p) => (
            <li key={p.id} className="card flex flex-col p-4">
              <div className="flex items-start gap-3">
                <Avatar name={p.display_name} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[16px] font-medium">{p.display_name}</p>
                  <p className="truncate font-mono text-[12px] text-muted">{p.id}</p>
                </div>
                {p.available === false ? <Badge tone="warn">Unavailable</Badge> : <Badge tone="ok" dot>Available</Badge>}
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {p.roles.map((r) => (
                  <Tag key={r}>{roleLabel(r)}</Tag>
                ))}
              </div>
              <dl className="mt-3 grid gap-1 text-[13px]">
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Now at</dt>
                  <dd className="truncate text-right">{locationLabel(pack.data, p.location_id)}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Listens for</dt>
                  <dd className="truncate text-right">{p.languages.stt_candidates.map(langLabel).join(", ")}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Asked in</dt>
                  <dd className="text-right">
                    {langLabel(p.languages.template_language)}
                    {p.languages.codemix ? " (mixed)" : ""}
                  </dd>
                </div>
              </dl>
              {!preview ? (
                <div className="mt-4 flex gap-2 border-t border-line pt-3">
                  <Button size="sm" onClick={() => setEditing(p)}>
                    <IconEdit className="h-4 w-4" /> Edit
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setRemoving(p)}>
                    <IconTrash className="h-4 w-4" /> Remove
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <Dialog
        wide
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Add participant" : "Edit participant"}
      >
        {editing !== null ? (
          <ParticipantForm
            initial={editing === "new" ? undefined : editing}
            pack={pack.data}
            existingIds={people.map((p) => p.id)}
            onCancel={() => setEditing(null)}
            onSubmit={(p) => {
              roster.upsert(p);
              setEditing(null);
            }}
          />
        ) : null}
      </Dialog>

      <Dialog
        open={!!removing}
        onClose={() => setRemoving(null)}
        title={`Remove ${removing?.display_name ?? ""}?`}
        description="They will no longer be offered for new investigations. Investigations that already include them are not affected."
        footer={
          <>
            <Button onClick={() => setRemoving(null)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => {
                if (removing) roster.remove(removing.id);
                setRemoving(null);
              }}
            >
              Remove
            </Button>
          </>
        }
      />
    </div>
  );
}
