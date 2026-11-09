# Workspace export and retention

Owners can download a workspace archive at any time. The streamed ZIP contains one JSON file per
data group and includes decrypted participant names and investigation reports. Treat it as personal
data. The export omits sessions, OAuth identities and tokens, invitation secrets, and person keys.
Each export is recorded in the workspace audit log.

Deleting a workspace sets `deleted_at`, `deleted_by`, and `purge_after` to 30 days in the future.
All ordinary workspace routes then return `410 WORKSPACE_DELETED`. An owner can download the export
or restore the workspace before `purge_after`. `/v1/me` keeps the deleted membership visible to
support routing while selecting only active workspaces as destinations.

## Scheduled purge

Deploy `scripts/purge_deleted_workspaces.py` as a daily job. Set its `DATABASE_URL` to a dedicated
non-superuser maintenance database role with `BYPASSRLS` and explicit table privileges for the purge
tables. Do not use the web service's `pramana_app` credentials. The command processes at most 25
workspaces per transaction and repeats until it has fewer than 25 due rows.

The job wraps and erases person data keys, then deletes personal ciphertext, consent, directory,
invitation, membership and idempotency rows. It removes question, observation and approval
projections and draft models, resets onboarding references, redacts mutable site descriptions and
names, and replaces the deleted organization name and slug. Published site models remain pinned and immutable for
investigation replay; the database permits the purge transaction to clear only their source and
validation metadata. The model spec and digest remain unchanged.

Events and audit rows are append-only. Before purging, the job checks that retained events do not
contain readable report or participant names. If it finds such a row, that workspace remains
unpurged and the job fails with `PURGE_REQUIRES_EVENT_REDACTION`; a reviewed migration is required
before retrying. The purge writes an `organization.purged` audit entry and does not remove events,
audit entries or pinned replay projections.

The maintenance schedule is a deployment requirement. Until the scheduled job is configured, owners
can still restore and export deleted workspaces, but workspaces past the retention date have not
been automatically purged.
