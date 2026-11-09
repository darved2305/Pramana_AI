"""Idempotently deploy the low-cost Cloud Run starter to the configured GCP project.

The default --dry-run prints the resource plan without reading credentials or contacting GCP.
Secret values travel through process memory and stdin to Secret Manager. They are never written to
the repository, a temporary file, a command argument, or this script's output.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DEFAULT = "luminous-slice-514102-f4"
REGION = "asia-south1"
INDIA_DATABASE_REGION = "ap-south-1"
NON_INDIA_DATABASE_ACK = "PRAMANA_ACCEPT_NON_INDIA_DATABASE"
TRUE_VALUES = frozenset({"true", "1", "yes"})
REPOSITORY = "pramana"
SERVICES = ("pramana-web", "pramana-core", "pramana-sim")
BUILD_ACCOUNT = "build"
SERVICE_ACCOUNTS = ("web", "core", "sim", "migrate", BUILD_ACCOUNT)
DEPLOY_ACCOUNT = "nikhilpise2006@gmail.com"
ALERT_BUDGET_NAME = "pramana-inr-1000"
LOG_FILTER = (
    '((resource.type="cloud_run_revision" AND resource.labels.location="asia-south1" AND '
    '(resource.labels.service_name="pramana-web" OR resource.labels.service_name="pramana-core" '
    'OR resource.labels.service_name="pramana-sim")) OR '
    '(resource.type="cloud_run_job" AND resource.labels.location="asia-south1" '
    'AND resource.labels.job_name="pramana-migrate"))'
)
API_SERVICES = (
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
)

SECRET_ENV = {
    "google-oauth-client-id": "GOOGLE_OAUTH_CLIENT_ID",
    "google-oauth-client-secret": "GOOGLE_OAUTH_CLIENT_SECRET",
    "gmail-address": "GMAIL_ADDRESS",
    "gmail-app-password": "GMAIL_APP_PASSWORD",
    "sim-operator-key": "SIM_OPERATOR_KEY",
    "participant-signing-key": "PARTICIPANT_SIGNING_KEY",
}
SECRET_ROTATABLE = frozenset(SECRET_ENV) | {
    "participant-public-key",
    "database-migrator-url",
    "database-runtime-url",
    "database-simulator-url",
}
ROTATION_ACKS = {
    "PRAMANA_SUPABASE_CREDENTIALS_ROTATED": "Supabase database password",
    "PRAMANA_SUPABASE_APP_PASSWORD_ROTATED": "Supabase runtime role password",
    "PRAMANA_SUPABASE_SECRET_KEY_ROTATED": "Supabase secret API key",
    "PRAMANA_GOOGLE_OAUTH_CLIENT_SECRET_ROTATED": "Google OAuth client secret",
    "PRAMANA_GMAIL_APP_PASSWORD_ROTATED": "Gmail app password",
}
# Stage-only exception: the owner has parked the credential rotations. It is accepted only
# together with the non-India database acknowledgement, so it can never describe a stage
# that holds real personal data, and it is printed on every deploy.
ROTATIONS_PARKED_ACK = "PRAMANA_ROTATIONS_PARKED"
MIN_PASSWORD_LENGTH = 16
DEPLOY_ENV_KEYS = frozenset(
    {
        "GCP_PROJECT_ID",
        "GCP_BILLING_ACCOUNT_ID",
        "PRAMANA_SUPABASE_REGION",
        "PRAMANA_SUPABASE_REF",
        "PRAMANA_SUPABASE_POOLER_HOST",
        "PRAMANA_SUPABASE_DATABASE",
        "PRAMANA_SUPABASE_DB_PASSWORD",
        "PRAMANA_SUPABASE_APP_PASSWORD",
        NON_INDIA_DATABASE_ACK,
        ROTATIONS_PARKED_ACK,
        *ROTATION_ACKS,
        *SECRET_ENV.values(),
    }
)


class DeployError(RuntimeError):
    """A precondition or deploy operation failed without displaying sensitive values."""


def dotenv_values(path: Path, *, allowed_keys: frozenset[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key not in allowed_keys:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def dry_run_environment() -> dict[str, str]:
    """Synthetic values for command planning. Never read project secrets for --dry-run."""
    values = {
        "GCP_PROJECT_ID": PROJECT_DEFAULT,
        "GCP_BILLING_ACCOUNT_ID": "000000-000000-000000",
        "PRAMANA_SUPABASE_REGION": "ap-south-1",
        "PRAMANA_SUPABASE_CREDENTIALS_ROTATED": "true",
        "PRAMANA_SUPABASE_APP_PASSWORD_ROTATED": "true",
        "PRAMANA_SUPABASE_SECRET_KEY_ROTATED": "true",
        "PRAMANA_GOOGLE_OAUTH_CLIENT_SECRET_ROTATED": "true",
        "PRAMANA_GMAIL_APP_PASSWORD_ROTATED": "true",
        "PRAMANA_SUPABASE_REF": "dryrunref123456",
        "PRAMANA_SUPABASE_POOLER_HOST": "aws-0-ap-south-1.pooler.supabase.com",
        "PRAMANA_SUPABASE_DATABASE": "postgres",
        "PRAMANA_SUPABASE_DB_PASSWORD": "dry-run-migrator-placeholder",
        "PRAMANA_SUPABASE_APP_PASSWORD": "dry-run-runtime-placeholder",
        "GOOGLE_OAUTH_CLIENT_ID": "dry-run-only-placeholder",
        "GOOGLE_OAUTH_CLIENT_SECRET": "dry-run-only-placeholder",
        "GMAIL_ADDRESS": "dry-run@example.invalid",
        "GMAIL_APP_PASSWORD": "dry-run-only-placeholder",
        "SIM_OPERATOR_KEY": "dry-run-only-placeholder",
        "PARTICIPANT_SIGNING_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    }
    return values


class Context:
    def __init__(self, args: argparse.Namespace, *, dry_run: bool = False) -> None:
        self.args = args
        if dry_run:
            self.env = dry_run_environment()
        else:
            self.env = dotenv_values(ROOT / ".env", allowed_keys=DEPLOY_ENV_KEYS)
            self.env.update(
                {key: value for key, value in os.environ.items() if key in DEPLOY_ENV_KEYS}
            )
        self.project = self.env.get("GCP_PROJECT_ID", PROJECT_DEFAULT)
        self.billing = self.env.get("GCP_BILLING_ACCOUNT_ID", "")
        self.sha = self.git_output("rev-parse", "--short=12", "HEAD").strip()
        self.image_root = f"{REGION}-docker.pkg.dev/{self.project}/{REPOSITORY}"
        self.py_image = f"{self.image_root}/pramana-py:{self.sha}"
        self.web_image = f"{self.image_root}/pramana-web:{self.sha}"
        self.urls: dict[str, str] = {}
        self.secret_values: dict[str, str] = {}
        self.service_urls: dict[str, str] = {}
        self.previous_traffic: dict[str, list[dict[str, Any]]] = {}

    def value(self, key: str, *, required: bool = True) -> str:
        value = self.env.get(key, "").strip()
        if required and not value:
            raise DeployError(f"required local .env setting is missing: {key}")
        return value

    def git_output(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise DeployError("git is required to identify the image SHA")
        return result.stdout


class Gcloud:
    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.binary = shutil.which("gcloud.cmd" if os.name == "nt" else "gcloud") or shutil.which(
            "gcloud"
        )
        if not dry_run and not self.binary:
            raise DeployError("gcloud is required; install the Google Cloud SDK")

    @staticmethod
    def display(args: Sequence[str]) -> str:
        return subprocess.list2cmdline(list(args)) if os.name == "nt" else shlex.join(args)

    def run(
        self,
        args: Sequence[str],
        *,
        input_data: str | bytes | None = None,
        check: bool = True,
        quiet: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        full = [self.binary or "gcloud", *args]
        display = self.display(full)
        if input_data is not None:
            display += " [secret payload via stdin]"
        print(f"$ {display}")
        if self.dry_run:
            return self._dry_result(args, full)
        if os.name == "nt" and str(self.binary).lower().endswith((".cmd", ".bat")):
            command: str | Sequence[str] = [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/d",
                "/s",
                "/c",
                f'call "{self.binary}" {subprocess.list2cmdline(list(args))}',
            ]
        else:
            command = full
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                input=input_data,
                capture_output=True,
                text=isinstance(input_data, str) or input_data is None,
                check=False,
            )
        except OSError as exc:
            raise DeployError("could not start gcloud") from exc
        if check and result.returncode:
            detail = result.stderr.strip() if not quiet else ""
            raise DeployError(f"gcloud command failed with exit {result.returncode}: {detail}")
        return result

    @staticmethod
    def _dry_result(args: Sequence[str], full: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(args)
        if command[:2] == ["auth", "list"]:
            return subprocess.CompletedProcess(full, 0, f"{DEPLOY_ACCOUNT}\n", "")
        if command[:2] == ["services", "list"]:
            return subprocess.CompletedProcess(full, 0, "[]\n", "")
        if command[:3] in (
            ["artifacts", "repositories", "describe"],
            ["logging", "buckets", "describe"],
            ["iam", "service-accounts", "describe"],
        ):
            return subprocess.CompletedProcess(full, 1, "", "not found in dry run")
        if command[:2] == ["secrets", "describe"]:
            return subprocess.CompletedProcess(full, 1, "", "not found in dry run")
        if command[:3] == ["logging", "sinks", "describe"]:
            if len(command) > 3 and command[3] == "_Default":
                return subprocess.CompletedProcess(full, 0, '{"exclusions": []}\n', "")
            return subprocess.CompletedProcess(full, 1, "", "not found in dry run")
        if command[:2] == ["projects", "describe"]:
            return subprocess.CompletedProcess(full, 0, "123456789\n", "")
        if command[:3] == ["run", "services", "describe"] and len(command) > 3:
            service = command[3]
            result = {
                "status": {
                    "url": f"https://{service}-dry-run.asia-south1.run.app",
                    "traffic": [],
                }
            }
            return subprocess.CompletedProcess(full, 0, json.dumps(result), "")
        return subprocess.CompletedProcess(full, 0, "", "")


def service_account_email(project: str, name: str) -> str:
    return f"pramana-{name}@{project}.iam.gserviceaccount.com"


def run_plan(ctx: Context) -> None:
    print("Budget deploy plan")
    print(f"Project: {ctx.project}")
    print(f"Region: {REGION}")
    print(f"Git SHA image tag: {ctx.sha}")
    print("Cloud Run services: public web (0-2), private core (0-2), private simulator (0-2).")
    print("Cloud Run job: private, one migration task, one retry disabled, 30 minute timeout.")
    print(
        "Database: Supabase Free in "
        f"{ctx.env.get('PRAMANA_SUPABASE_REGION', 'an unconfigured region')} with separate "
        "migrator, core and simulator roles."
    )
    print("Secrets: 11 regional Secret Manager secrets; values are hidden.")
    print("Images: two Cloud Build SHA tags; keep five rollback versions.")
    print("Budget: existing INR 1,000 project alert, recorded by name; no spend cap is created.")
    print("Logs: asia-south1 bucket, 180 day retention; only Pramana services routed.")
    print("Not planned: Cloud SQL, load balancer, Cloud Armor, NAT, media or worker services.")
    print("Synthetic settings are used below. --dry-run does not read .env secrets or contact GCP.")
    execute(Gcloud(dry_run=True), ctx)


def validate_environment(ctx: Context) -> None:
    if ctx.project != PROJECT_DEFAULT:
        raise DeployError(f"GCP_PROJECT_ID must be {PROJECT_DEFAULT}")
    region = ctx.value("PRAMANA_SUPABASE_REGION").lower()
    if not re.fullmatch(r"[a-z]{2}-[a-z]+-[0-9]", region):
        raise DeployError(
            "PRAMANA_SUPABASE_REGION must be a Supabase AWS region such as ap-south-1"
        )
    accepted = ctx.value(NON_INDIA_DATABASE_ACK, required=False).lower() in TRUE_VALUES
    if region != INDIA_DATABASE_REGION and not accepted:
        raise DeployError(
            f"the Supabase project is in {region}, not {INDIA_DATABASE_REGION} (Mumbai). Real "
            "personal data must not be stored there. For a stage with no real personal data, "
            f"set {NON_INDIA_DATABASE_ACK}=true in .env to accept this explicitly"
        )
    outstanding = [
        (setting, label)
        for setting, label in ROTATION_ACKS.items()
        if ctx.value(setting, required=False).lower() not in TRUE_VALUES
    ]
    if outstanding:
        parked = ctx.value(ROTATIONS_PARKED_ACK, required=False).lower() in TRUE_VALUES
        if region == INDIA_DATABASE_REGION or not accepted or not parked:
            setting, label = outstanding[0]
            raise DeployError(
                f"Darshan must rotate {label} and set {setting}=true before deployment. "
                f"A stage with parked rotations needs {NON_INDIA_DATABASE_ACK}=true and "
                f"{ROTATIONS_PARKED_ACK}=true, and must hold no real personal data."
            )
        print(
            "WARNING: credential rotations are parked; these credentials are still the "
            "pre-rotation values: " + ", ".join(label for _, label in outstanding) + "."
        )
    if not re.fullmatch(r"[A-Za-z0-9-]{6,64}", ctx.value("PRAMANA_SUPABASE_REF")):
        raise DeployError("PRAMANA_SUPABASE_REF has an invalid format")
    host = ctx.value("PRAMANA_SUPABASE_POOLER_HOST").lower()
    if not re.fullmatch(r"[a-z0-9.-]+\.pooler\.supabase\.com", host) or f"-{region}." not in host:
        raise DeployError(f"PRAMANA_SUPABASE_POOLER_HOST must be the {region} session pooler host")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}-[0-9A-Fa-f]{6}-[0-9A-Fa-f]{6}", ctx.billing):
        raise DeployError("set GCP_BILLING_ACCOUNT_ID in the local .env file")
    for name in SECRET_ENV.values():
        ctx.value(name)
    try:
        signing_seed = base64.urlsafe_b64decode(ctx.value("PARTICIPANT_SIGNING_KEY") + "==")
    except (ValueError, base64.binascii.Error) as exc:
        raise DeployError("PARTICIPANT_SIGNING_KEY must encode a 32-byte Ed25519 seed") from exc
    if len(signing_seed) != 32:
        raise DeployError("PARTICIPANT_SIGNING_KEY must encode a 32-byte Ed25519 seed")
    short = [
        label
        for setting, label in (
            ("PRAMANA_SUPABASE_DB_PASSWORD", "migrator"),
            ("PRAMANA_SUPABASE_APP_PASSWORD", "runtime"),
        )
        if len(ctx.value(setting)) < MIN_PASSWORD_LENGTH
    ]
    if short and not outstanding:
        raise DeployError(
            f"the rotated Supabase {short[0]} password is too short; use at least "
            f"{MIN_PASSWORD_LENGTH} characters"
        )
    if short:
        print(
            "WARNING: parked credentials are shorter than the "
            f"{MIN_PASSWORD_LENGTH}-character rule: "
            + ", ".join(f"{name} password" for name in short)
        )
    if ctx.value("PRAMANA_SUPABASE_APP_PASSWORD") == ctx.value("PRAMANA_SUPABASE_DB_PASSWORD"):
        raise DeployError("Supabase migrator and runtime passwords must be different")
    ctx.value("PRAMANA_SUPABASE_DATABASE")


def database_urls(ctx: Context, sim_password: str) -> dict[str, str]:
    ref = ctx.value("PRAMANA_SUPABASE_REF")
    host = ctx.value("PRAMANA_SUPABASE_POOLER_HOST")
    dbname = ctx.env.get("PRAMANA_SUPABASE_DATABASE", "postgres")

    def make(role: str, password: str) -> str:
        return URL.create(
            "postgresql+asyncpg",
            username=f"{role}.{ref}",
            password=password,
            host=host,
            port=5432,
            database=dbname,
            query={"ssl": "require"},
        ).render_as_string(hide_password=False)

    return {
        "database-migrator-url": make("postgres", ctx.value("PRAMANA_SUPABASE_DB_PASSWORD")),
        "database-runtime-url": make("pramana_app", ctx.value("PRAMANA_SUPABASE_APP_PASSWORD")),
        "database-simulator-url": make("pramana_sim", sim_password),
    }


def check_gcloud_account(gcloud: Gcloud, ctx: Context) -> None:
    # Read-only: the billing account cannot be described with the deploy identity, so the
    # INR currency of the existing budget is recorded by the owner, not checked here.
    result = gcloud.run(
        ["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], quiet=True
    )
    if DEPLOY_ACCOUNT not in result.stdout.split():
        raise DeployError(
            f"the active gcloud account must be {DEPLOY_ACCOUNT}; the owner signs in with "
            "`gcloud auth login` before deploying"
        )


def enable_apis(gcloud: Gcloud, ctx: Context) -> None:
    result = gcloud.run(
        ["services", "list", "--enabled", "--format=json", f"--project={ctx.project}"], quiet=True
    )
    enabled = {entry.get("config", {}).get("name") for entry in json.loads(result.stdout or "[]")}
    missing = [api for api in API_SERVICES if api not in enabled]
    if missing:
        gcloud.run(["services", "enable", *missing, f"--project={ctx.project}", "--quiet"])
    else:
        print("Required APIs are already enabled.")


def ensure_artifact_registry(gcloud: Gcloud, ctx: Context) -> None:
    exists = gcloud.run(
        [
            "artifacts",
            "repositories",
            "describe",
            REPOSITORY,
            f"--location={REGION}",
            f"--project={ctx.project}",
        ],
        check=False,
        quiet=True,
    )
    if exists.returncode:
        gcloud.run(
            [
                "artifacts",
                "repositories",
                "create",
                REPOSITORY,
                f"--location={REGION}",
                "--repository-format=docker",
                "--description=Pramana SHA-tagged deployment images",
                f"--project={ctx.project}",
                "--quiet",
            ]
        )
    policy = [
        {
            "name": "delete-untagged-after-7-days",
            "action": {"type": "Delete"},
            "condition": {"tagState": "UNTAGGED", "olderThan": "604800s"},
        },
        {
            "name": "delete-tagged-after-90-days",
            "action": {"type": "Delete"},
            "condition": {
                "tagState": "TAGGED",
                "packageNamePrefixes": ["pramana-py", "pramana-web"],
                "olderThan": "7776000s",
            },
        },
        {
            "name": "keep-five-rollback-versions",
            "action": {"type": "Keep"},
            "mostRecentVersions": {
                "packageNamePrefixes": ["pramana-py", "pramana-web"],
                "keepCount": 5,
            },
        },
    ]
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".json", delete=False, dir=ROOT
    ) as file:
        temp_path = Path(file.name)
        json.dump(policy, file, separators=(",", ":"))
    try:
        gcloud.run(
            [
                "artifacts",
                "set-cleanup-policies",
                REPOSITORY,
                f"--location={REGION}",
                f"--policy={temp_path}",
                "--no-dry-run",
                f"--project={ctx.project}",
                "--quiet",
            ]
        )
    finally:
        temp_path.unlink(missing_ok=True)


def ensure_logging(gcloud: Gcloud, ctx: Context) -> None:
    bucket = gcloud.run(
        [
            "logging",
            "buckets",
            "describe",
            "pramana-run",
            f"--location={REGION}",
            f"--project={ctx.project}",
            "--format=json",
        ],
        check=False,
        quiet=True,
    )
    if bucket.returncode:
        gcloud.run(
            [
                "logging",
                "buckets",
                "create",
                "pramana-run",
                f"--location={REGION}",
                "--retention-days=180",
                "--description=Pramana Cloud Run service and migration logs",
                f"--project={ctx.project}",
                "--quiet",
            ]
        )
    else:
        parsed = json.loads(bucket.stdout or "{}")
        if parsed.get("location") != REGION:
            raise DeployError("existing pramana-run log bucket is not in asia-south1")
        if int(parsed.get("retentionDays", 0)) != 180:
            gcloud.run(
                [
                    "logging",
                    "buckets",
                    "update",
                    "pramana-run",
                    f"--location={REGION}",
                    "--retention-days=180",
                    f"--project={ctx.project}",
                    "--quiet",
                ]
            )

    destination = (
        f"logging.googleapis.com/projects/{ctx.project}/locations/{REGION}/buckets/pramana-run"
    )
    sink = gcloud.run(
        [
            "logging",
            "sinks",
            "describe",
            "pramana-run",
            f"--project={ctx.project}",
            "--format=json",
        ],
        check=False,
        quiet=True,
    )
    if sink.returncode:
        gcloud.run(
            [
                "logging",
                "sinks",
                "create",
                "pramana-run",
                destination,
                f"--log-filter={LOG_FILTER}",
                f"--project={ctx.project}",
                "--quiet",
            ]
        )
    else:
        parsed = json.loads(sink.stdout or "{}")
        if parsed.get("destination") != destination or parsed.get("filter") != LOG_FILTER:
            gcloud.run(
                [
                    "logging",
                    "sinks",
                    "update",
                    "pramana-run",
                    destination,
                    f"--log-filter={LOG_FILTER}",
                    f"--project={ctx.project}",
                    "--quiet",
                ]
            )

    default = json.loads(
        gcloud.run(
            [
                "logging",
                "sinks",
                "describe",
                "_Default",
                f"--project={ctx.project}",
                "--format=json",
            ],
            quiet=True,
        ).stdout
        or "{}"
    )
    exclusions = default.get("exclusions", [])
    entry = next((e for e in exclusions if e.get("name") == "pramana-run"), None)
    if entry is None:
        gcloud.run(
            [
                "logging",
                "sinks",
                "update",
                "_Default",
                f"--add-exclusion=name=pramana-run,filter={LOG_FILTER}",
                f"--project={ctx.project}",
                "--quiet",
            ]
        )
    elif entry.get("filter") != LOG_FILTER or entry.get("disabled") is True:
        gcloud.run(
            [
                "logging",
                "sinks",
                "update",
                "_Default",
                f"--update-exclusion=name=pramana-run,filter={LOG_FILTER}",
                f"--project={ctx.project}",
                "--quiet",
            ]
        )


def ensure_service_accounts(gcloud: Gcloud, ctx: Context) -> None:
    for account in SERVICE_ACCOUNTS:
        email = service_account_email(ctx.project, account)
        exists = gcloud.run(
            ["iam", "service-accounts", "describe", email, f"--project={ctx.project}"],
            check=False,
            quiet=True,
        )
        if exists.returncode:
            gcloud.run(
                [
                    "iam",
                    "service-accounts",
                    "create",
                    f"pramana-{account}",
                    f"--display-name=Pramana {account}",
                    f"--project={ctx.project}",
                    "--quiet",
                ]
            )


def ensure_secret(
    gcloud: Gcloud,
    ctx: Context,
    name: str,
    proposed: str | None,
    *,
    rotate: bool,
) -> str:
    secret = f"pramana-{name}"
    exists = gcloud.run(
        ["secrets", "describe", secret, f"--project={ctx.project}"], check=False, quiet=True
    )
    if exists.returncode:
        gcloud.run(
            [
                "secrets",
                "create",
                secret,
                "--replication-policy=user-managed",
                f"--locations={REGION}",
                f"--project={ctx.project}",
                "--quiet",
            ]
        )
        if proposed is None:
            raise DeployError(f"a first secret value is required for {secret}")
        gcloud.run(
            ["secrets", "versions", "add", secret, "--data-file=-", f"--project={ctx.project}"],
            input_data=proposed,
            quiet=True,
        )
        return proposed

    current = gcloud.run(
        [
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={secret}",
            f"--project={ctx.project}",
        ],
        quiet=True,
    ).stdout.rstrip("\r\n")
    if proposed is None:
        return current
    if current == proposed:
        return current
    if not rotate:
        raise DeployError(f"{secret} already has a different value; pass --rotate-secret {name}")
    gcloud.run(
        ["secrets", "versions", "add", secret, "--data-file=-", f"--project={ctx.project}"],
        input_data=proposed,
        quiet=True,
    )
    return proposed


def ensure_secrets(gcloud: Gcloud, ctx: Context) -> None:
    requested = set(ctx.args.rotate_secret or [])
    invalid = requested - SECRET_ROTATABLE
    if invalid:
        raise DeployError("unknown or protected secret rotation requested")
    if "pii-key" in requested:
        raise DeployError("PRAMANA_PII_KEY cannot be rotated by this deploy script")
    if "participant-signing-key" in requested:
        requested.add("participant-public-key")

    signing = ctx.value("PARTICIPANT_SIGNING_KEY")
    try:
        from pramana_contracts.tokens import private_key_from_b64, public_key_b64

        public = public_key_b64(private_key_from_b64(signing))
    except (ValueError, TypeError) as exc:
        raise DeployError("PARTICIPANT_SIGNING_KEY is invalid") from exc
    proposed: dict[str, str | None] = {
        name: ctx.value(env_name) for name, env_name in SECRET_ENV.items()
    }
    proposed.update(
        {
            "participant-public-key": public,
            "pii-key": None,
        }
    )
    pii_exists = (
        gcloud.run(
            ["secrets", "describe", "pramana-pii-key", f"--project={ctx.project}"],
            check=False,
            quiet=True,
        ).returncode
        == 0
    )
    if not pii_exists:
        proposed["pii-key"] = secrets.token_urlsafe(32)

    sim_password: str
    sim_secret_name = "pramana-database-simulator-url"
    sim_exists = (
        gcloud.run(
            ["secrets", "describe", sim_secret_name, f"--project={ctx.project}"],
            check=False,
            quiet=True,
        ).returncode
        == 0
    )
    sim_existing: str | None = None
    if sim_exists and "database-simulator-url" not in requested:
        sim_existing = gcloud.run(
            [
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={sim_secret_name}",
                f"--project={ctx.project}",
            ],
            quiet=True,
        ).stdout.rstrip("\r\n")
        try:
            current = make_url(sim_existing)
            if (
                current.host != ctx.value("PRAMANA_SUPABASE_POOLER_HOST")
                or current.username != f"pramana_sim.{ctx.value('PRAMANA_SUPABASE_REF')}"
                or not current.password
            ):
                raise DeployError(
                    "database-simulator-url targets a different pooler; pass "
                    "--rotate-secret database-simulator-url"
                )
            sim_password = current.password or ""
        except (ValueError, TypeError) as exc:
            raise DeployError("stored simulator database URL is invalid") from exc
    else:
        sim_password = secrets.token_urlsafe(32)

    urls = database_urls(ctx, sim_password)
    proposed.update(urls)
    values: dict[str, str] = {}
    for name, value in proposed.items():
        values[name] = ensure_secret(
            gcloud,
            ctx,
            name,
            value,
            rotate=name in requested,
        )
    ctx.secret_values = values
    ctx.urls = {name: values[name] for name in urls}


def secret_bindings(gcloud: Gcloud, ctx: Context) -> None:
    access = {
        "web": (),
        "core": (
            "pii-key",
            "google-oauth-client-id",
            "google-oauth-client-secret",
            "gmail-address",
            "gmail-app-password",
            "sim-operator-key",
            "participant-signing-key",
            "database-runtime-url",
        ),
        "sim": ("sim-operator-key", "participant-public-key", "database-simulator-url"),
        "migrate": ("database-migrator-url", "database-runtime-url", "database-simulator-url"),
    }
    for account, names in access.items():
        member = f"serviceAccount:{service_account_email(ctx.project, account)}"
        for name in names:
            gcloud.run(
                [
                    "secrets",
                    "add-iam-policy-binding",
                    f"pramana-{name}",
                    f"--member={member}",
                    "--role=roles/secretmanager.secretAccessor",
                    f"--project={ctx.project}",
                    "--quiet",
                ]
            )


def record_budget(ctx: Context) -> None:
    """Record the owner-created budget. This script never lists, creates or changes budgets.

    The INR 1,000 project alert was created by the billing owner (issue #7) because the deploy
    identity has no billing role. A Cloud Run spend cap is not created here for the same reason.
    """
    print(
        f"Budget: existing monthly INR 1,000 alert '{ALERT_BUDGET_NAME}' on billing account "
        f"{ctx.billing}, scoped to project {ctx.project}, thresholds 50%, 80% and 100% of "
        "actual spend. Created by the billing owner; not read or changed by this script."
    )
    print(
        "Cloud Run spend cap: not configured by this script. Cost is bounded by minimum 0 "
        "instances, maximum 2 per service, request-based billing and the Artifact Registry "
        "cleanup policy. The alert does not cap spend."
    )


def build_bucket(ctx: Context) -> str:
    return f"{ctx.project}-pramana-build"


def ensure_build_identity(gcloud: Gcloud, ctx: Context) -> None:
    """Give the dedicated build account only what a regional Cloud Build needs.

    Cloud Build uses this account instead of the project's default Compute Engine account,
    which has no roles in this project. It can write logs, push images to the Pramana
    repository, and read and write only its own source staging bucket, which expires objects
    after seven days.
    """
    bucket = build_bucket(ctx)
    member = f"serviceAccount:{service_account_email(ctx.project, BUILD_ACCOUNT)}"
    exists = gcloud.run(
        ["storage", "buckets", "describe", f"gs://{bucket}", f"--project={ctx.project}"],
        check=False,
        quiet=True,
    )
    if exists.returncode:
        gcloud.run(
            [
                "storage",
                "buckets",
                "create",
                f"gs://{bucket}",
                f"--location={REGION}",
                "--uniform-bucket-level-access",
                "--public-access-prevention",
                f"--project={ctx.project}",
            ]
        )
    lifecycle = [{"action": {"type": "Delete"}, "condition": {"age": 7}}]
    lifecycle_path = write_temp_json(lifecycle)
    try:
        gcloud.run(
            [
                "storage",
                "buckets",
                "update",
                f"gs://{bucket}",
                f"--lifecycle-file={lifecycle_path}",
                f"--project={ctx.project}",
            ]
        )
    finally:
        lifecycle_path.unlink(missing_ok=True)
    gcloud.run(
        [
            "projects",
            "add-iam-policy-binding",
            ctx.project,
            f"--member={member}",
            "--role=roles/logging.logWriter",
            "--condition=None",
            "--quiet",
        ],
        quiet=True,
    )
    gcloud.run(
        [
            "artifacts",
            "repositories",
            "add-iam-policy-binding",
            REPOSITORY,
            f"--location={REGION}",
            f"--member={member}",
            "--role=roles/artifactregistry.writer",
            f"--project={ctx.project}",
            "--quiet",
        ],
        quiet=True,
    )
    gcloud.run(
        [
            "storage",
            "buckets",
            "add-iam-policy-binding",
            f"gs://{bucket}",
            f"--member={member}",
            "--role=roles/storage.objectAdmin",
            f"--project={ctx.project}",
            "--quiet",
        ],
        quiet=True,
    )


def write_temp_json(payload: object) -> Path:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".json", delete=False, dir=ROOT
    ) as file:
        json.dump(payload, file, separators=(",", ":"))
    return Path(file.name)


def build_images(gcloud: Gcloud, ctx: Context) -> None:
    email = service_account_email(ctx.project, BUILD_ACCOUNT)
    account = f"projects/{ctx.project}/serviceAccounts/{email}"
    bucket = build_bucket(ctx)
    common = [
        f"--region={REGION}",
        f"--project={ctx.project}",
        f"--service-account={account}",
        f"--gcs-source-staging-dir=gs://{bucket}/source",
        f"--gcs-log-dir=gs://{bucket}/logs",
        "--quiet",
    ]
    gcloud.run(["builds", "submit", ".", f"--tag={ctx.py_image}", *common])
    gcloud.run(["builds", "submit", "apps/web", f"--tag={ctx.web_image}", *common])


def service_describe(gcloud: Gcloud, ctx: Context, name: str) -> dict[str, Any] | None:
    result = gcloud.run(
        [
            "run",
            "services",
            "describe",
            name,
            f"--region={REGION}",
            f"--project={ctx.project}",
            "--format=json",
        ],
        check=False,
        quiet=True,
    )
    if result.returncode:
        return None
    return json.loads(result.stdout or "{}")


def remember_traffic(gcloud: Gcloud, ctx: Context) -> None:
    for name in SERVICES:
        service = service_describe(gcloud, ctx, name)
        if service:
            ctx.previous_traffic[name] = service.get("status", {}).get("traffic", [])


def rollback_commands(ctx: Context) -> list[list[str]]:
    commands: list[list[str]] = []
    for name in SERVICES:
        traffic = ctx.previous_traffic.get(name) or []
        if not traffic:
            continue
        revision = next(
            (
                entry.get("revisionName")
                for entry in traffic
                if entry.get("percent", 0) > 0 and entry.get("revisionName")
            ),
            None,
        )
        if revision:
            commands.append(
                [
                    "run",
                    "services",
                    "update-traffic",
                    name,
                    f"--to-revisions={revision}=100",
                    f"--region={REGION}",
                    f"--project={ctx.project}",
                    "--quiet",
                ]
            )
    return commands


def deploy_service(
    gcloud: Gcloud,
    ctx: Context,
    *,
    name: str,
    image: str,
    account: str,
    env_vars: dict[str, str],
    secrets: dict[str, str],
    memory: str,
    concurrency: int,
    timeout: str,
    probe_path: str,
    public: bool,
    max_instances: int = 2,
    no_traffic: bool = False,
) -> str:
    envs = ",".join(f"{key}={value}" for key, value in env_vars.items())
    secret_map = ",".join(f"{key}=pramana-{secret}:latest" for key, secret in secrets.items())
    args = [
        "run",
        "deploy",
        name,
        f"--image={image}",
        f"--region={REGION}",
        f"--project={ctx.project}",
        "--platform=managed",
        f"--service-account={service_account_email(ctx.project, account)}",
        "--min=0",
        f"--max={max_instances}",
        "--cpu=1",
        f"--memory={memory}",
        f"--concurrency={concurrency}",
        f"--timeout={timeout}",
        "--cpu-throttling",
        "--execution-environment=gen2",
        f"--set-env-vars={envs}",
        f"--startup-probe=httpGet.path={probe_path},periodSeconds=10,timeoutSeconds=5,failureThreshold=18",
        f"--readiness-probe=httpGet.path={probe_path},periodSeconds=10,timeoutSeconds=5,failureThreshold=3",
        f"--liveness-probe=httpGet.path={probe_path},periodSeconds=60,timeoutSeconds=5,failureThreshold=3",
        "--quiet",
    ]
    if secret_map:
        args.append(f"--set-secrets={secret_map}")
    args.append("--allow-unauthenticated" if public else "--no-allow-unauthenticated")
    # --no-traffic keeps the serving revision live while a new one is prepared. A brand-new
    # service has no serving revision to keep, and Cloud Run rejects the flag for it.
    if no_traffic and service_describe(gcloud, ctx, name) is not None:
        args.append("--no-traffic")
    gcloud.run(args)
    described = service_describe(gcloud, ctx, name)
    url = (described or {}).get("status", {}).get("url")
    if not url:
        raise DeployError(f"Cloud Run did not return a URL for {name}")
    ctx.service_urls[name] = url.rstrip("/")
    return ctx.service_urls[name]


def deploy_migrator(gcloud: Gcloud, ctx: Context) -> None:
    gcloud.run(
        [
            "run",
            "jobs",
            "deploy",
            "pramana-migrate",
            f"--image={ctx.py_image}",
            "--args=migrate",
            f"--region={REGION}",
            f"--project={ctx.project}",
            f"--service-account={service_account_email(ctx.project, 'migrate')}",
            "--tasks=1",
            "--parallelism=1",
            "--max-retries=0",
            "--task-timeout=1800s",
            "--set-secrets=DATABASE_URL=pramana-database-migrator-url:latest,DATABASE_RUNTIME_URL=pramana-database-runtime-url:latest,DATABASE_SIMULATOR_URL=pramana-database-simulator-url:latest",
            "--quiet",
        ]
    )
    gcloud.run(
        [
            "run",
            "jobs",
            "execute",
            "pramana-migrate",
            f"--region={REGION}",
            f"--project={ctx.project}",
            "--wait",
            "--quiet",
        ]
    )


def bind_invoker(gcloud: Gcloud, ctx: Context, service: str, account: str) -> None:
    gcloud.run(
        [
            "run",
            "services",
            "add-iam-policy-binding",
            service,
            f"--member=serviceAccount:{service_account_email(ctx.project, account)}",
            "--role=roles/run.invoker",
            f"--region={REGION}",
            f"--project={ctx.project}",
            "--quiet",
        ]
    )


def smoke(gcloud: Gcloud, ctx: Context) -> None:
    base = ctx.service_urls["pramana-web"]
    if gcloud.dry_run:
        print(f"HTTP GET {base}/ (planned; live smoke skipped in dry-run)")
        print(f"HTTP GET {base}/login (planned; live smoke skipped in dry-run)")
        print(f"HTTP GET {base}/_next/static/... (planned; live smoke skipped in dry-run)")
        print(
            f"HTTP GET {base}/api/core/health and {base}/ready "
            "(planned; live smoke skipped in dry-run)"
        )
        return

    def get(path: str) -> tuple[int, bytes, str]:
        req = urllib.request.Request(base + path, headers={"User-Agent": "pramana-deploy-smoke/1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status, response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type", "")

    status, home, _ = get("/")
    if status != 200:
        raise DeployError("web home smoke check failed")
    status, login, _ = get("/login")
    if status != 200 or b"Continue with Google" not in login:
        raise DeployError("sign-in page smoke check failed")
    match = re.search(rb'(?:src|href)="(/_next/static/[^"?]+)', home)
    if not match:
        raise DeployError("web HTML did not include a static Next asset")
    asset_status, _, _ = get(match.group(1).decode())
    if asset_status != 200:
        raise DeployError("static asset smoke check failed")
    core_status, core_body, _ = get("/api/core/health")
    if core_status != 200 or b'"status":"ok"' not in core_body:
        raise DeployError("core proxy smoke check failed")
    ready_status, ready_body, _ = get("/ready")
    if ready_status != 200 or b'"status":"ready"' not in ready_body:
        raise DeployError("readiness smoke check failed")
    print("Live smoke passed: /, /login, a Next static asset, /api/core/health and /ready.")


def execute(gcloud: Gcloud, ctx: Context) -> None:
    validate_environment(ctx)
    region = ctx.value("PRAMANA_SUPABASE_REGION").lower()
    if region != INDIA_DATABASE_REGION:
        print(
            f"WARNING: the Supabase database is in {region}, outside India. It is accepted by "
            f"{NON_INDIA_DATABASE_ACK}=true for a stage with no real personal data only."
        )
    check_gcloud_account(gcloud, ctx)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if status.returncode:
        raise DeployError("git is required to identify a clean SHA-tagged release")
    if status.stdout.strip() and not gcloud.dry_run:
        raise DeployError("commit the worktree before deploying a SHA-tagged release")
    if status.stdout.strip():
        print(
            "Dry-run plans current HEAD only; uncommitted changes are excluded from the SHA image."
        )

    enable_apis(gcloud, ctx)
    ensure_artifact_registry(gcloud, ctx)
    ensure_logging(gcloud, ctx)
    ensure_service_accounts(gcloud, ctx)
    record_budget(ctx)
    ensure_secrets(gcloud, ctx)
    secret_bindings(gcloud, ctx)
    remember_traffic(gcloud, ctx)
    ensure_build_identity(gcloud, ctx)
    build_images(gcloud, ctx)
    deploy_migrator(gcloud, ctx)

    # Keep prior web traffic active while learning the managed URL for backend configuration.
    web_url = deploy_service(
        gcloud,
        ctx,
        name="pramana-web",
        image=ctx.web_image,
        account="web",
        env_vars={
            "NEXT_PUBLIC_ENABLE_PREVIEW": "0",
            "PRAMANA_CORE_URL": "http://127.0.0.1:9",
            "PRAMANA_SIM_URL": "http://127.0.0.1:9",
            "PRAMANA_CLOUD_RUN_AUTH": "true",
        },
        secrets={},
        memory="512Mi",
        concurrency=40,
        timeout="300s",
        probe_path="/",
        public=True,
        no_traffic=True,
    )
    sim_url = deploy_service(
        gcloud,
        ctx,
        name="pramana-sim",
        image=ctx.py_image,
        account="sim",
        env_vars={
            "PRAMANA_MODE": "production",
            "SIM_DATABASE_POOL_SIZE": "1",
            "SIM_MAX_SCENARIOS": "500",
            "SIM_REQUIRE_DOCUMENTED_MODELS": "true",
        },
        secrets={
            "SIM_DATABASE_URL": "database-simulator-url",
            "SIM_OPERATOR_KEY": "sim-operator-key",
            "SIM_PARTICIPANT_PUBLIC_KEY": "participant-public-key",
        },
        memory="512Mi",
        concurrency=40,
        timeout="300s",
        probe_path="/ready",
        public=False,
    )
    bind_invoker(gcloud, ctx, "pramana-sim", "web")
    bind_invoker(gcloud, ctx, "pramana-sim", "core")
    core_url = deploy_service(
        gcloud,
        ctx,
        name="pramana-core",
        image=ctx.py_image,
        account="core",
        env_vars={
            "PRAMANA_MODE": "production",
            "AUTH_REQUIRED": "true",
            "SESSION_COOKIE_SECURE": "true",
            "SIM_URL": sim_url,
            "SIM_PUBLIC_URL": f"{web_url}/api/sim",
            "SIM_SERVERLESS_AUTH": "true",
            "DB_POOL_SIZE": "3",
            "DB_MAX_OVERFLOW": "0",
            "DB_POOL_TIMEOUT_S": "5",
            "PUBLIC_WEB_URL": web_url,
            "OIDC_REDIRECT_URL": f"{web_url}/api/core/v1/auth/google/callback",
            "LLM_EXTRACTOR_PROVIDER": "none",
            "LOG_JSON": "true",
            "LOG_LEVEL": "INFO",
            "RECOVER_ON_STARTUP": "true",
            "EVAL_REPORTS_DIR": "/tmp/eval-reports",
        },
        secrets={
            "DATABASE_URL": "database-runtime-url",
            "PRAMANA_PII_KEY": "pii-key",
            "GOOGLE_OAUTH_CLIENT_ID": "google-oauth-client-id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "google-oauth-client-secret",
            "GMAIL_ADDRESS": "gmail-address",
            "GMAIL_APP_PASSWORD": "gmail-app-password",
            "SIM_OPERATOR_KEY": "sim-operator-key",
            "PARTICIPANT_SIGNING_KEY": "participant-signing-key",
        },
        memory="1Gi",
        concurrency=8,
        timeout="3600s",
        probe_path="/ready",
        public=False,
    )
    bind_invoker(gcloud, ctx, "pramana-core", "web")
    web_url = deploy_service(
        gcloud,
        ctx,
        name="pramana-web",
        image=ctx.web_image,
        account="web",
        env_vars={
            "NEXT_PUBLIC_ENABLE_PREVIEW": "0",
            "PRAMANA_CORE_URL": core_url,
            "PRAMANA_SIM_URL": sim_url,
            "PRAMANA_CLOUD_RUN_AUTH": "true",
        },
        secrets={},
        memory="512Mi",
        concurrency=40,
        timeout="300s",
        probe_path="/",
        public=True,
    )
    smoke(gcloud, ctx)
    print(f"Web URL: {web_url}")
    print(f"Google OAuth authorized redirect URI: {web_url}/api/core/v1/auth/google/callback")
    print("Rollback commands for prior traffic:")
    commands = rollback_commands(ctx)
    if commands:
        for command in commands:
            print("$ " + Gcloud.display([gcloud.binary or "gcloud", *command]))
    else:
        print("No prior revisions existed. Redeploy the previous image SHA to roll back.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="print the resource plan without GCP access"
    )
    parser.add_argument(
        "--rotate-secret",
        action="append",
        default=[],
        metavar="NAME",
        help="explicitly add a Secret Manager version for a named secret",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        ctx = Context(args, dry_run=args.dry_run)
        if args.dry_run:
            run_plan(ctx)
            return
        execute(Gcloud(), ctx)
    except DeployError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
