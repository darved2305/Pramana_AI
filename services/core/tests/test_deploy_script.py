from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "deploy_gcp_starter.py"
SPEC = importlib.util.spec_from_file_location("pramana_deploy_script", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
deploy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = deploy
SPEC.loader.exec_module(deploy)
assert isinstance(deploy, ModuleType)


def test_dry_run_uses_synthetic_values_and_never_reads_env_or_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("dry-run must not read .env values or make HTTP requests")

    monkeypatch.setattr(deploy, "dotenv_values", forbidden)
    monkeypatch.setattr(deploy.urllib.request, "urlopen", forbidden)
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)

    deploy.run_plan(context)

    output = capsys.readouterr().out
    assert "--locations=asia-south1" in output
    assert "--no-traffic" in output
    assert "run jobs execute pramana-migrate" in output
    assert "X-Serverless-Authorization" not in output
    assert "dry-run-only-placeholder" not in output
    assert "Budget: existing INR 1,000 project alert" in output
    assert "planned; live smoke skipped in dry-run" in output
    assert "DB_POOL_SIZE=3" in output
    assert "DB_POOL_SIZE=6" not in output
    assert "DB_MAX_OVERFLOW=0" in output
    assert "SIM_DATABASE_POOL_SIZE=1" in output


def test_deploy_context_discards_unrelated_environment_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = {
        "GCP_PROJECT_ID": deploy.PROJECT_DEFAULT,
        "DATABASE_URL": "unrelated-db-value",
        "SUPABASE_ACCESS_TOKEN": "unrelated-token-value",
    }
    monkeypatch.setattr(
        deploy,
        "dotenv_values",
        lambda _path, *, allowed_keys: {
            key: value for key, value in supplied.items() if key in allowed_keys
        },
    )
    context = deploy.Context(Namespace(rotate_secret=[]))

    assert context.env["GCP_PROJECT_ID"] == deploy.PROJECT_DEFAULT
    assert "DATABASE_URL" not in context.env
    assert "SUPABASE_ACCESS_TOKEN" not in context.env


def test_dotenv_parser_returns_only_deploy_settings() -> None:
    path = deploy.ROOT / ".deploy-env-test"
    path.write_text(
        "GCP_PROJECT_ID=luminous-slice-514102-f4\n"
        "DATABASE_URL=unrelated-db-value\n"
        "SUPABASE_ACCESS_TOKEN=unrelated-token-value\n",
        encoding="utf-8",
    )
    try:
        values = deploy.dotenv_values(path, allowed_keys=deploy.DEPLOY_ENV_KEYS)
    finally:
        path.unlink(missing_ok=True)

    assert values == {"GCP_PROJECT_ID": deploy.PROJECT_DEFAULT}


def test_deployment_requires_the_named_rotation_acknowledgements() -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)
    context.env["PRAMANA_GMAIL_APP_PASSWORD_ROTATED"] = "false"

    with pytest.raises(deploy.DeployError, match="Gmail app password"):
        deploy.validate_environment(context)


def test_non_india_database_needs_an_explicit_acknowledgement() -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)
    context.env["PRAMANA_SUPABASE_REGION"] = "ap-southeast-1"
    context.env["PRAMANA_SUPABASE_POOLER_HOST"] = "aws-0-ap-southeast-1.pooler.supabase.com"
    context.env[deploy.NON_INDIA_DATABASE_ACK] = "false"

    with pytest.raises(deploy.DeployError, match=r"not ap-south-1 .* Real personal data"):
        deploy.validate_environment(context)

    context.env[deploy.NON_INDIA_DATABASE_ACK] = "false"
    with pytest.raises(deploy.DeployError, match="Real personal data"):
        deploy.validate_environment(context)

    context.env[deploy.NON_INDIA_DATABASE_ACK] = "true"
    deploy.validate_environment(context)


def test_deployment_refuses_an_unrelated_supabase_project() -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)
    context.env["PRAMANA_SUPABASE_REF"] = "llpjrfugwktlaizmxrtq"

    with pytest.raises(deploy.DeployError, match="authorized Pramana project"):
        deploy.validate_environment(context)


def test_pooler_host_must_belong_to_the_configured_database_region() -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)
    context.env["PRAMANA_SUPABASE_REGION"] = "ap-southeast-1"
    context.env["PRAMANA_SUPABASE_POOLER_HOST"] = "aws-0-ap-south-1.pooler.supabase.com"
    context.env[deploy.NON_INDIA_DATABASE_ACK] = "true"

    with pytest.raises(deploy.DeployError, match="ap-southeast-1 session pooler host"):
        deploy.validate_environment(context)


def test_budget_is_recorded_by_name_and_never_created_or_read(
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)

    deploy.record_budget(context)

    output = capsys.readouterr().out
    assert f"'{deploy.ALERT_BUDGET_NAME}'" in output
    assert "thresholds 50%, 80% and 100%" in output
    assert "not read or changed by this script" in output
    assert not hasattr(deploy, "ensure_budget")


def test_live_script_never_calls_billing_or_forbidden_identity_commands() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        '"billing"',
        '"budgets"',
        '"print-access-token"',
        '"login"',
        '"application-default"',
        '"revoke"',
        '"activate-service-account"',
        "billingbudgets",
        "--impersonate",
    ):
        assert forbidden not in source, forbidden


def test_parked_rotations_need_the_stage_acknowledgements(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def parked_context(region: str, host: str) -> deploy.Context:
        context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)
        for setting in deploy.ROTATION_ACKS:
            context.env[setting] = "false"
        context.env["PRAMANA_SUPABASE_REGION"] = region
        context.env["PRAMANA_SUPABASE_POOLER_HOST"] = host
        return context

    singapore = "aws-0-ap-southeast-1.pooler.supabase.com"
    context = parked_context("ap-southeast-1", singapore)
    context.env[deploy.NON_INDIA_DATABASE_ACK] = "true"
    with pytest.raises(deploy.DeployError, match="Darshan must rotate"):
        deploy.validate_environment(context)

    context.env[deploy.ROTATIONS_PARKED_ACK] = "true"
    deploy.validate_environment(context)
    warning = capsys.readouterr().out
    assert "credential rotations are parked" in warning
    assert "Supabase database password" in warning

    india = parked_context("ap-south-1", "aws-0-ap-south-1.pooler.supabase.com")
    india.env[deploy.ROTATIONS_PARKED_ACK] = "true"
    with pytest.raises(deploy.DeployError, match="Darshan must rotate"):
        deploy.validate_environment(india)


def test_runbook_states_budget_and_missing_spend_cap() -> None:
    runbook = (deploy.ROOT / "docs" / "engineering" / "DEPLOY_BUDGET_GCP.md").read_text(
        encoding="utf-8"
    )
    assert f"`{deploy.ALERT_BUDGET_NAME}`" in runbook
    assert "50%, 80% and 100%" in runbook
    assert "No Cloud Run spend cap is configured" in runbook
    assert "50%, 90%" not in runbook


def test_backup_runbook_checks_native_command_exit_codes() -> None:
    runbook = (deploy.ROOT / "docs" / "engineering" / "DEPLOY_BUDGET_GCP.md").read_text(
        encoding="utf-8"
    )
    for command in ("pg_dump", "age encryption", "age decryption", "pg_restore", "grant audit"):
        assert f"{command} failed" in runbook
    assert "if ($LASTEXITCODE -ne 0)" in runbook


def test_private_service_accounts_receive_only_their_database_secret() -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)

    class Recorder:
        dry_run = True

        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(self, args: list[str], **_kwargs: object) -> None:
            self.commands.append(args)

    recorder = Recorder()
    deploy.secret_bindings(recorder, context)
    bindings = [" ".join(command) for command in recorder.commands]
    core_bindings = [entry for entry in bindings if "pramana-core@" in entry]
    sim_bindings = [entry for entry in bindings if "pramana-sim@" in entry]
    web_bindings = [entry for entry in bindings if "pramana-web@" in entry]

    assert any("pramana-database-runtime-url" in entry for entry in core_bindings)
    assert not any("pramana-database-migrator-url" in entry for entry in core_bindings)
    assert not any("pramana-database-simulator-url" in entry for entry in core_bindings)
    assert any("pramana-database-simulator-url" in entry for entry in sim_bindings)
    assert not any("pramana-database-migrator-url" in entry for entry in sim_bindings)
    assert web_bindings == []


def test_images_are_built_by_the_dedicated_build_account_and_bucket() -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)

    class Recorder:
        dry_run = True

        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(self, args: list[str], **_kwargs: object) -> None:
            self.commands.append(args)

    recorder = Recorder()
    deploy.build_images(recorder, context)
    builds = [command for command in recorder.commands if command[:2] == ["builds", "submit"]]
    account = f"pramana-build@{deploy.PROJECT_DEFAULT}.iam.gserviceaccount.com"

    assert len(builds) == 2
    for command in builds:
        assert f"--service-account=projects/{deploy.PROJECT_DEFAULT}/serviceAccounts/{account}" in (
            command
        )
        assert f"--gcs-source-staging-dir=gs://{deploy.build_bucket(context)}/source" in command
        assert f"--gcs-log-dir=gs://{deploy.build_bucket(context)}/logs" in command


def test_short_parked_passwords_warn_but_rotated_passwords_must_be_long(
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)
    context.env["PRAMANA_SUPABASE_DB_PASSWORD"] = "short-1"
    context.env[deploy.NON_INDIA_DATABASE_ACK] = "true"
    for setting in deploy.ROTATION_ACKS:
        context.env[setting] = "false"
    context.env[deploy.ROTATIONS_PARKED_ACK] = "true"
    context.env["PRAMANA_SUPABASE_REGION"] = "ap-southeast-1"
    context.env["PRAMANA_SUPABASE_POOLER_HOST"] = "aws-0-ap-southeast-1.pooler.supabase.com"

    deploy.validate_environment(context)
    assert "migrator password" in capsys.readouterr().out

    for setting in deploy.ROTATION_ACKS:
        context.env[setting] = "true"
    with pytest.raises(deploy.DeployError, match="too short"):
        deploy.validate_environment(context)


def test_gcloud_passes_quoted_log_filters_as_one_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gcloud = deploy.Gcloud.__new__(deploy.Gcloud)
    gcloud.dry_run = False
    gcloud.binary = "gcloud.cmd"
    gcloud.prefix = ["bundled-python", "gcloud.py"]
    gcloud.env = None
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **_kwargs: object) -> deploy.subprocess.CompletedProcess[str]:
        captured["command"] = command
        return deploy.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(deploy.subprocess, "run", fake_run)
    gcloud.run(["logging", "read", deploy.LOG_FILTER, "--limit=1"], quiet=True)

    assert captured["command"] == [
        "bundled-python",
        "gcloud.py",
        "logging",
        "read",
        deploy.LOG_FILTER,
        "--limit=1",
    ]


def test_sdk_root_is_found_from_the_launcher_or_a_shim(tmp_path: Path) -> None:
    sdk = tmp_path / "google-cloud-sdk"
    (sdk / "bin").mkdir(parents=True)
    (sdk / "lib").mkdir()
    launcher = sdk / "bin" / "gcloud.cmd"
    launcher.write_text("@rem launcher\n", encoding="utf-8")
    (sdk / "lib" / "gcloud.py").write_text("", encoding="utf-8")
    assert deploy.sdk_root_from_launcher(launcher) == sdk

    shim_dir = tmp_path / "shims"
    shim_dir.mkdir()
    shim = shim_dir / "gcloud.cmd"
    shim.write_text(f'@"{launcher}"  %*\n', encoding="utf-8")
    assert deploy.sdk_root_from_launcher(shim) == sdk
