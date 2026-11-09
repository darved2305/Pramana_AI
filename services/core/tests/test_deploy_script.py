from __future__ import annotations

import importlib.util
import io
import json
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
    assert "Spend cap request body:" in output
    assert "planned; live smoke skipped in dry-run" in output


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


def test_existing_alert_budget_with_wrong_amount_fails_closed() -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)

    class ExistingBudgetCloud:
        dry_run = False

        def run(self, args: list[str], **_kwargs: object):
            if args[:2] == ["projects", "describe"]:
                return deploy.subprocess.CompletedProcess(args, 0, "123456789\n", "")
            assert args[:3] == ["billing", "budgets", "list"]
            return deploy.subprocess.CompletedProcess(
                args,
                0,
                '[{"displayName":"Pramana monthly project alert INR 1000",'
                '"budgetFilter":{"projects":["projects/luminous-slice-514102-f4"],'
                '"calendarPeriod":"MONTH"},"amount":{"specifiedAmount":'
                '{"currencyCode":"INR","units":"100"}},"thresholdRules":[]}]',
                "",
            )

    with pytest.raises(deploy.DeployError, match="different scope or amount"):
        deploy.ensure_budget(ExistingBudgetCloud(), context)


def test_existing_alert_budget_with_project_number_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    context = deploy.Context(Namespace(rotate_secret=[]), dry_run=True)
    budgets = [
        {
            "displayName": deploy.ALERT_BUDGET_NAME,
            "budgetFilter": {
                "projects": ["projects/123456789"],
                "calendarPeriod": "MONTH",
            },
            "amount": {"specifiedAmount": {"currencyCode": "INR", "units": "1000"}},
            "thresholdRules": [{"thresholdPercent": value} for value in (0.5, 0.8, 1.0)],
        },
        {
            "displayName": deploy.SPEND_CAP_NAME,
            "budgetFilter": {
                "projects": ["projects/123456789"],
                "services": [f"services/{deploy.RUN_SERVICE_ID}"],
                "calendarPeriod": "MONTH",
            },
            "amount": {"specifiedAmount": {"currencyCode": "INR", "units": "500"}},
            "thresholdRules": [{"thresholdPercent": value} for value in (0.5, 0.8, 1.0)],
            "spendCap": {"inputState": "CONFIGURED"},
        },
    ]

    class ExistingBudgetCloud:
        dry_run = False

        def run(self, args: list[str], **_kwargs: object):
            if args[:2] == ["projects", "describe"]:
                return deploy.subprocess.CompletedProcess(args, 0, "123456789\n", "")
            if args[:3] == ["billing", "budgets", "list"]:
                return deploy.subprocess.CompletedProcess(args, 0, json.dumps([budgets[0]]), "")
            if args[:2] == ["auth", "print-access-token"]:
                return deploy.subprocess.CompletedProcess(args, 0, "token\n", "")
            raise AssertionError(f"unexpected gcloud call: {args}")

    monkeypatch.setattr(
        deploy.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(json.dumps({"budgets": [budgets[1]]}).encode()),
    )
    deploy.ensure_budget(ExistingBudgetCloud(), context)

    assert "Cloud Run spend cap already has the expected project, service and amount." in (
        capsys.readouterr().out
    )


def test_runbook_describes_project_wide_cloud_run_cap() -> None:
    runbook = (deploy.ROOT / "docs" / "engineering" / "DEPLOY_BUDGET_GCP.md").read_text(
        encoding="utf-8"
    )
    assert "applies to all Cloud Run resource types" in runbook
    assert "including services and jobs" in runbook
    assert "products and projects keep running" in runbook


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
