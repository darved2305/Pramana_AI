"""Workspace domain claims and requests to join.

Revision ID: 0018
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0018"
down_revision = "0016"
branch_labels = None
depends_on = None

ORG = "nullif(current_setting('app.org_id', true), '')::uuid"
USER = "nullif(current_setting('app.user_id', true), '')"
HOSTED_DOMAIN = "lower(nullif(current_setting('app.hosted_domain', true), ''))"
MANAGER = (
    "exists (select 1 from memberships m where m.org_id = {org_id} "
    f"and m.user_id = {USER} and m.status = 'active' "
    "and m.roles && array['owner', 'admin']::text[])"
)


def upgrade() -> None:
    op.add_column("sessions", sa.Column("hosted_domain", sa.String(253), nullable=True))

    op.create_table(
        "org_domains",
        sa.Column(
            "org_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("domain", sa.String(253), primary_key=True),
        sa.Column("verification", sa.String(16), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("join_policy", sa.String(16), nullable=False, server_default="request"),
        sa.Column("verification_token", sa.String(64), nullable=True),
        sa.Column(
            "added_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("domain = lower(domain)", name="org_domains_lowercase"),
        sa.CheckConstraint(
            "verification in ('google_hd', 'dns_txt')", name="org_domains_verification"
        ),
        sa.CheckConstraint(
            "join_policy in ('off', 'request', 'auto')", name="org_domains_join_policy"
        ),
        sa.CheckConstraint(
            "verification_token is null or verification_token ~ '^[A-Za-z0-9_-]{32,64}$'",
            name="org_domains_verification_token",
        ),
    )
    op.create_index(
        "org_domains_verified_once",
        "org_domains",
        ["domain"],
        unique=True,
        postgresql_where=sa.text("verified_at is not null"),
    )
    op.execute("alter table org_domains enable row level security")
    op.execute("alter table org_domains force row level security")
    manager = MANAGER.format(org_id="org_domains.org_id")
    op.execute(
        "create policy org_domains_manager_read on org_domains for select using "
        f"(org_id = {ORG} and {manager})"
    )
    op.execute(
        "create policy org_domains_verified_read on org_domains for select using "
        "(verified_at is not null and join_policy in ('request', 'auto') "
        f"and domain = {HOSTED_DOMAIN} "
        f"and exists (select 1 from users u where u.id = {USER} "
        "and u.email_verified_at is not null "
        "and lower(split_part(u.email, '@', 2)) = org_domains.domain))"
    )
    op.execute(
        "create policy org_domains_manager_insert on org_domains for insert with check "
        f"(org_id = {ORG} and {manager})"
    )
    op.execute(
        "create policy org_domains_manager_update on org_domains for update "
        f"using (org_id = {ORG} and {manager}) "
        f"with check (org_id = {ORG} and {manager})"
    )
    op.execute(
        "create policy org_domains_manager_delete on org_domains for delete using "
        f"(org_id = {ORG} and {manager})"
    )

    op.create_table(
        "join_requests",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("roles", pg.ARRAY(sa.Text()), nullable=True),
        sa.Column("decision_source", sa.String(16), nullable=True),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('pending', 'approved', 'declined', 'cancelled')",
            name="join_requests_status",
        ),
        sa.CheckConstraint(
            "roles is null or (cardinality(roles) > 0 and "
            "roles <@ array['admin', 'operator', 'approver', 'viewer']::text[])",
            name="join_requests_roles",
        ),
        sa.CheckConstraint(
            "decision_source is null or decision_source in ('admin', 'auto')",
            name="join_requests_decision_source",
        ),
        sa.CheckConstraint(
            "(status = 'pending' and decided_at is null and decision_source is null) or "
            "(status <> 'pending' and decided_at is not null)",
            name="join_requests_decided",
        ),
    )
    op.create_index(
        "join_requests_pending_person",
        "join_requests",
        ["org_id", "requester_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("join_requests_org_recent", "join_requests", ["org_id", "requested_at"])
    op.create_index(
        "join_requests_requester_recent", "join_requests", ["requester_id", "requested_at"]
    )
    op.execute("alter table join_requests enable row level security")
    op.execute("alter table join_requests force row level security")
    op.execute(
        "create policy join_requests_requester_read on join_requests for select using "
        f"(requester_id = {USER})"
    )
    op.execute(
        "create policy join_requests_admin_read on join_requests for select using "
        f"(org_id = {ORG} and {MANAGER.format(org_id='join_requests.org_id')})"
    )
    request_domain = (
        "exists (select 1 from org_domains d join organizations o on o.id = d.org_id "
        f"join users u on u.id = {USER} where d.org_id = join_requests.org_id "
        "and d.verified_at is not null and d.join_policy = 'request' "
        f"and lower(d.domain) = {HOSTED_DOMAIN} "
        "and lower(split_part(u.email, '@', 2)) = lower(d.domain) "
        "and u.email_verified_at is not null and o.deleted_at is null)"
    )
    auto_domain = (
        "exists (select 1 from org_domains d join organizations o on o.id = d.org_id "
        f"join users u on u.id = {USER} where d.org_id = join_requests.org_id "
        "and d.verified_at is not null and d.join_policy = 'auto' "
        f"and lower(d.domain) = {HOSTED_DOMAIN} "
        "and lower(split_part(u.email, '@', 2)) = lower(d.domain) "
        "and u.email_verified_at is not null and o.deleted_at is null)"
    )
    op.execute(
        "create policy join_requests_requester_insert on join_requests for insert with check "
        f"(requester_id = {USER} and decided_by is null and "
        f"((status = 'pending' and roles is null and decision_source is null and {request_domain}) "
        f"or (status = 'approved' and roles = array['viewer']::text[] "
        f"and decision_source = 'auto' and {auto_domain})))"
    )
    op.execute(
        "create policy join_requests_requester_cancel on join_requests for update "
        f"using (requester_id = {USER} and status = 'pending') "
        f"with check (requester_id = {USER} and status = 'cancelled')"
    )
    op.execute(
        "create policy join_requests_admin_update on join_requests for update "
        f"using (org_id = {ORG} and status = 'pending' and "
        f"{MANAGER.format(org_id='join_requests.org_id')}) "
        f"with check (org_id = {ORG} and {MANAGER.format(org_id='join_requests.org_id')})"
    )
    # RLS checks rows, not which columns an UPDATE changes. A requester who can
    # cancel must not be able to move the row or forge the decision metadata.
    op.execute(
        f"""create function guard_join_request_cancellation() returns trigger
        language plpgsql as $$
        begin
          if old.requester_id = {USER}
             and not coalesce((old.org_id = {ORG} and {MANAGER.format(org_id='old.org_id')}), false) then
            if new.id is distinct from old.id
               or new.org_id is distinct from old.org_id
               or new.requester_id is distinct from old.requester_id
               or new.decided_by is distinct from old.decided_by
               or new.roles is distinct from old.roles
               or new.requested_at is distinct from old.requested_at
               or new.status <> 'cancelled'
               or (new.decision_source is not null and new.decision_source <> 'auto') then
              raise exception 'requesters may only cancel their own join requests'
                using errcode = '42501';
            end if;
          end if;
          return new;
        end $$"""
    )
    op.execute(
        "create trigger guard_join_request_cancellation before update on join_requests "
        "for each row execute function guard_join_request_cancellation()"
    )

    # A domain suggestion can reveal only the workspace that owns the user's own verified `hd`.
    op.execute(
        "create policy organization_domain_suggestion on organizations for select using ("
        "exists (select 1 from org_domains d join users u on u.id = "
        f"{USER} where d.org_id = organizations.id and d.verified_at is not null "
        "and d.join_policy in ('request', 'auto') "
        f"and lower(d.domain) = {HOSTED_DOMAIN} "
        "and lower(split_part(u.email, '@', 2)) = lower(d.domain) "
        "and u.email_verified_at is not null and organizations.deleted_at is null)"
        ")"
    )

    op.execute(
        """do $$ begin
          if exists (select 1 from pg_roles where rolname = 'pramana_app') then
            grant select, insert, update, delete on org_domains to pramana_app;
            grant select, insert, update on join_requests to pramana_app;
          end if;
          if exists (select 1 from pg_roles where rolname = 'anon') then
            revoke all on org_domains, join_requests from anon;
          end if;
          if exists (select 1 from pg_roles where rolname = 'authenticated') then
            revoke all on org_domains, join_requests from authenticated;
          end if;
        end $$;"""
    )


def downgrade() -> None:
    op.execute("drop policy organization_domain_suggestion on organizations")
    op.drop_table("join_requests")
    op.execute("drop function if exists guard_join_request_cancellation()")
    op.drop_table("org_domains")
    op.drop_column("sessions", "hosted_domain")
