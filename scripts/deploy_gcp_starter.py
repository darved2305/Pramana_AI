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
REPOSITORY = "pramana"
SERVICES = ("pramana-web", "pramana-core", "pramana-sim")
SERVICE_ACCOUNTS = ("web", "core", "sim", "migrate")
RUN_SERVICE_ID = "152E-C115-5142"
ALERT_BUDGET_NAME = "Pramana monthly project alert INR 1000"
SPEND_CAP_NAME = "Pramana Cloud Run spend cap INR 500"
LOG_FILTER = (
    '((resource.type="cloud_run_revision" AND resource.labels.location="asia-south1" AND '
    '(resource.labels.service_name="pramana-web" OR resource.labels.service_name="pramana-core" '
    'OR resource.labels.service_name="pramana-sim")) OR '
    '(resource.type="cloud_run_job" AND resource.labels.location="asia-south1" '
    'AND resource.labels.job_name="pramana-migrate"))'
)
API_SERVICES = (
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
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
            return subprocess.CompletedProcess(full, 0, "dry-run-account\n", "")
        if command[:3] == ["billing", "accounts", "describe"]:
            return subprocess.CompletedProcess(full, 0, "INR\n", "")
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
        if command[:3] == ["billing", "budgets", "list"]:
            return subprocess.CompletedProcess(full, 0, "[]\n", "")
        if command[:2] == ["projects", "describe"]:
            return subprocess.CompletedProcess(full, 0, "123456789\n", "")
        if command[:2] == ["auth", "print-access-token"]:
            return subprocess.CompletedProcess(full, 0, "dry-run-token\n", "")
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
    print("Database: Supabase Free in Mumbai with separate migrator, core and simulator roles.")
    print("Secrets: 11 regional Secret Manager secrets; values are hidden.")
    print("Images: two Cloud Build SHA tags; keep five rollback versions.")
    print("Budgets: INR 1,000 project alert and INR 500 Cloud Run spend cap when eligible.")
    print("Logs: asia-south1 bucket, 180 day retention; only Pramana services routed.")
    print("Not planned: Cloud SQL, load balancer, Cloud Armor, NAT, media or worker services.")
    print("Synthetic settings are used below. --dry-run does not read .env secrets or contact GCP.")
    execute(Gcloud(dry_run=True), ctx)


def validate_environment(ctx: Context) -> None:
    if ctx.project != PROJECT_DEFAULT:
        raise DeployError(f"GCP_PROJECT_ID must be {PROJECT_DEFAULT}")
    if ctx.value("PRAMANA_SUPABASE_REGION") != "ap-south-1":
        raise DeployError(
            "move the Pramana Supabase project to ap-south-1 before deploying real data"
        )
    for setting, label in ROTATION_ACKS.items():
        if ctx.value(setting).lower() not in {"true", "1", "yes"}:
            raise DeployError(
                f"Darshan must rotate {label} and set {setting}=true before deployment"
            )
    if not re.fullmatch(r"[A-Za-z0-9-]{6,64}", ctx.value("PRAMANA_SUPABASE_REF")):
        raise DeployError("PRAMANA_SUPABASE_REF has an invalid format")
    host = ctx.value("PRAMANA_SUPABASE_POOLER_HOST").lower()
    if not re.fullmatch(r"[a-z0-9.-]+\.pooler\.supabase\.com", host) or "ap-south-1" not in host:
        raise DeployError("PRAMANA_SUPABASE_POOLER_HOST must be the ap-south-1 session pooler host")
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
    if len(ctx.value("PRAMANA_SUPABASE_DB_PASSWORD")) < 16:
        raise DeployError("the rotated Supabase migrator password is missing or too short")
    if len(ctx.value("PRAMANA_SUPABASE_APP_PASSWORD")) < 16:
        raise DeployError("the rotated Supabase runtime password is missing or too short")
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
    result = gcloud.run(
        ["auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], quiet=True
    )
    if not result.stdout.strip():
        raise DeployError("no active gcloud account; run `gcloud auth login` first")
    currency = gcloud.run(
        [
            "billing",
            "accounts",
            "describe",
            ctx.billing,
            "--format=value(currencyCode)",
            f"--project={ctx.project}",
        ],
        quiet=True,
    ).stdout.strip()
    if currency != "INR":
        raise DeployError(
            "the linked billing account must use INR for the configured budget limits"
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


def ensure_budget(gcloud: Gcloud, ctx: Context) -> None:
    project_number = gcloud.run(
        [
            "projects",
            "describe",
            ctx.project,
            "--format=value(projectNumber)",
            f"--project={ctx.project}",
        ],
        quiet=True,
    ).stdout.strip()
    if not project_number:
        raise DeployError("project number unavailable for Cloud Run spend cap")

    found = gcloud.run(
        [
            "billing",
            "budgets",
            "list",
            f"--billing-account={ctx.billing}",
            "--format=json",
            f"--project={ctx.project}",
        ],
        quiet=True,
    )
    budgets = json.loads(found.stdout or "[]")
    alert = next((item for item in budgets if item.get("displayName") == ALERT_BUDGET_NAME), None)
    if alert is None:
        gcloud.run(
            [
                "billing",
                "budgets",
                "create",
                f"--billing-account={ctx.billing}",
                f"--display-name={ALERT_BUDGET_NAME}",
                "--budget-amount=1000INR",
                "--calendar-period=month",
                f"--filter-projects=projects/{ctx.project}",
                "--threshold-rule=percent=0.50",
                "--threshold-rule=percent=0.80",
                "--threshold-rule=percent=1.00",
                f"--project={ctx.project}",
                "--quiet",
            ]
        )
    else:
        filter_ = alert.get("budgetFilter", {})
        amount = alert.get("amount", {}).get("specifiedAmount", {})
        thresholds = {rule.get("thresholdPercent") for rule in alert.get("thresholdRules", [])}
        project_scopes = set(filter_.get("projects", []))
        if (
            not project_scopes.intersection(
                {f"projects/{ctx.project}", f"projects/{project_number}"}
            )
            or filter_.get("calendarPeriod") != "MONTH"
            or amount.get("currencyCode") != "INR"
            or amount.get("units") != "1000"
            or thresholds != {0.5, 0.8, 1.0}
        ):
            raise DeployError(
                "existing project alert budget has different scope or amount; review it manually"
            )
        print("The project alert budget already has the expected scope, amount and thresholds.")

    try:
        url = f"https://billingbudgets.googleapis.com/v1/billingAccounts/{ctx.billing}/budgets"
        body: dict[str, Any] = {
            "displayName": SPEND_CAP_NAME,
            "budgetFilter": {
                "projects": [f"projects/{project_number}"],
                "services": [f"services/{RUN_SERVICE_ID}"],
                "creditTypesTreatment": "EXCLUDE_ALL_CREDITS",
                "calendarPeriod": "MONTH",
            },
            "amount": {"specifiedAmount": {"currencyCode": "INR", "units": "500", "nanos": 0}},
            "thresholdRules": [
                {"thresholdPercent": 0.5, "spendBasis": "CURRENT_SPEND"},
                {"thresholdPercent": 0.8, "spendBasis": "CURRENT_SPEND"},
                {"thresholdPercent": 1.0, "spendBasis": "CURRENT_SPEND"},
            ],
            "notificationsRule": {"enableProjectLevelRecipients": True},
            "ownershipScope": "ALL_USERS",
            "spendCap": {"inputState": "CONFIGURED"},
        }
        if gcloud.dry_run:
            print(f"REST GET {url} (synthetic dry-run; no network request)")
            print(f"REST POST {url} (synthetic dry-run; no network request)")
            print(f"Spend cap request body: {json.dumps(body, sort_keys=True)}")
        else:
            token = gcloud.run(["auth", "print-access-token"], quiet=True).stdout.strip()
            if not token:
                raise DeployError("access token unavailable for Cloud Run spend cap")
            headers = {
                "Authorization": f"Bearer {token}",
                "x-goog-user-project": ctx.project,
                "Content-Type": "application/json",
            }
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as response:
                existing = json.load(response).get("budgets", [])
            match = next(
                (item for item in existing if item.get("displayName") == SPEND_CAP_NAME), None
            )
            if match:
                filter_ = match.get("budgetFilter", {})
                amount = match.get("amount", {}).get("specifiedAmount", {})
                thresholds = {
                    rule.get("thresholdPercent") for rule in match.get("thresholdRules", [])
                }
                if (
                    f"projects/{project_number}" not in filter_.get("projects", [])
                    or f"services/{RUN_SERVICE_ID}" not in filter_.get("services", [])
                    or filter_.get("calendarPeriod") != "MONTH"
                    or amount.get("currencyCode") != "INR"
                    or amount.get("units") != "500"
                    or match.get("spendCap", {}).get("inputState") != "CONFIGURED"
                    or thresholds != {0.5, 0.8, 1.0}
                ):
                    raise DeployError(
                        "existing Cloud Run spend cap has different scope, amount or thresholds; "
                        "review it manually"
                    )
                print("Cloud Run spend cap already has the expected project, service and amount.")
            else:
                req = urllib.request.Request(
                    url, data=json.dumps(body).encode(), headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    response.read()
                print("Cloud Run spend cap created at INR 500 before tax.")
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        KeyError,
    ) as exc:
        print(
            "Warning: Cloud Run spend cap could not be configured for this billing account "
            f"({type(exc).__name__}); the INR 1,000 alert remains active."
        )


def build_images(gcloud: Gcloud, ctx: Context) -> None:
    gcloud.run(
        [
            "builds",
            "submit",
            ".",
            f"--region={REGION}",
            f"--tag={ctx.py_image}",
            f"--project={ctx.project}",
            "--quiet",
        ]
    )
    gcloud.run(
        [
            "builds",
            "submit",
            "apps/web",
            f"--region={REGION}",
            f"--tag={ctx.web_image}",
            f"--project={ctx.project}",
            "--quiet",
        ]
    )


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
    if no_traffic:
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
    ensure_budget(gcloud, ctx)
    ensure_secrets(gcloud, ctx)
    secret_bindings(gcloud, ctx)
    remember_traffic(gcloud, ctx)
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
            "DB_POOL_SIZE": "1",
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
        concurrency=20,
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
