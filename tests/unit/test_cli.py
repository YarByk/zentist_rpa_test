from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from portal_automation import __main__ as cli
from portal_automation.core.models import RunResult, RunStatus

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ConfigStub:
    db_path: str
    artifacts_dir: str
    business_date: str | None = None
    headless: bool = True
    orangehrm_password: str | None = None
    saucedemo_password: str | None = None
    email_backend: str = "dry_run"
    report_email_to: str | None = None
    stale_item_timeout_seconds: int = 300
    orangehrm_input_path: str = "data/orangehrm_employees.json"
    saucedemo_input_path: str = "data/saucedemo_accounts.json"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    smtp_use_tls: bool = True


class RunnerStub:
    calls = []

    def run(self, context):
        self.calls.append(context)
        return RunResult(
            run_id=context.run_id,
            portal_name="stub",
            business_date=context.business_date,
            status=RunStatus.SUCCESS,
            results=[],
        )


class OrangeRunnerStub(RunnerStub):
    calls = []


class SauceRunnerStub(RunnerStub):
    calls = []


def configure_cli(monkeypatch, tmp_path):
    OrangeRunnerStub.calls = []
    SauceRunnerStub.calls = []
    config = ConfigStub(
        db_path=str(tmp_path / "portal.sqlite"),
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    runner_map = {
        "orangehrm": OrangeRunnerStub,
        "saucedemo": SauceRunnerStub,
    }
    monkeypatch.setattr(cli.AppConfig, "from_env", classmethod(lambda cls: config))
    monkeypatch.setattr(cli, "PORTAL_RUNNERS", runner_map)
    monkeypatch.setattr(cli, "get_runner", lambda portal_name: runner_map[portal_name])
    return config


def test_top_level_help_exits_zero(capsys) -> None:
    exit_code = cli.main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage:" in captured.out


@pytest.mark.parametrize("portal_name", ["orangehrm", "saucedemo", "all", "recover"])
def test_subcommand_help_exits_zero(portal_name, capsys) -> None:
    exit_code = cli.main([portal_name, "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage:" in captured.out


def test_unknown_portal_exits_nonzero_and_lists_available_portals(capsys) -> None:
    exit_code = cli.main(["unknown"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "orangehrm" in captured.err
    assert "saucedemo" in captured.err
    assert "all" in captured.err


def test_business_date_argument_is_parsed_into_date(monkeypatch, tmp_path) -> None:
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm", "--dry-run", "--business-date", "2026-06-29"])

    assert exit_code == 0
    assert OrangeRunnerStub.calls[0].business_date == date(2026, 6, 29)


def test_invalid_business_date_exits_nonzero(capsys) -> None:
    exit_code = cli.main(["orangehrm", "--business-date", "06-29-2026"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "YYYY-MM-DD" in captured.err


def test_headless_argument_overrides_config(monkeypatch, tmp_path) -> None:
    config = configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm", "--dry-run", "--headless", "false"])

    assert exit_code == 0
    assert config.headless is True
    assert OrangeRunnerStub.calls[0].config.headless is False


def test_email_backend_argument_overrides_config(monkeypatch, tmp_path) -> None:
    config = configure_cli(monkeypatch, tmp_path)
    config.smtp_host = "smtp.example.com"
    config.smtp_from = "reports@example.com"
    config.report_email_to = "reviewer@example.com"

    exit_code = cli.main(["orangehrm", "--dry-run", "--email-backend", "smtp"])

    assert exit_code == 0
    assert OrangeRunnerStub.calls[0].config.email_backend == "smtp"


def test_smtp_backend_missing_required_config_fails_fast(monkeypatch, tmp_path, capsys) -> None:
    config = configure_cli(monkeypatch, tmp_path)
    config.email_backend = "smtp"

    exit_code = cli.main(["orangehrm", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "SMTP backend is selected" in captured.err


def test_single_portal_run_uses_only_selected_registry_runner(monkeypatch, tmp_path) -> None:
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm", "--dry-run"])

    assert exit_code == 0
    assert len(OrangeRunnerStub.calls) == 1
    assert SauceRunnerStub.calls == []


def test_runtime_path_uses_secrets_loader_for_selected_portal(monkeypatch, tmp_path) -> None:
    configure_cli(monkeypatch, tmp_path)
    calls = []

    class LoaderStub:
        def __init__(self, config) -> None:
            self.config = config

        def get(self, key: str):
            calls.append(("get", key))
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            return None

        def require(self, key: str):
            calls.append(("require", key))
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            raise AssertionError(f"unexpected secret lookup: {key}")

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)

    exit_code = cli.main(["orangehrm"])

    assert exit_code == 0
    assert OrangeRunnerStub.calls[0].config.orangehrm_password == "loaded-orange-secret"
    assert ("get", "ORANGEHRM_PASSWORD") in calls
    assert ("require", "ORANGEHRM_PASSWORD") in calls


def test_non_dry_run_missing_selected_portal_secret_fails_fast(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ORANGEHRM_PASSWORD is required for this runtime path." in captured.err


def test_all_executes_both_portals_in_sorted_order(monkeypatch, tmp_path) -> None:
    order = []
    configure_cli(monkeypatch, tmp_path)

    class OrangeRecorder(OrangeRunnerStub):
        def run(self, context):
            order.append("orangehrm")
            return super().run(context)

    class SauceRecorder(SauceRunnerStub):
        def run(self, context):
            order.append("saucedemo")
            return super().run(context)

    runner_map = {
        "saucedemo": SauceRecorder,
        "orangehrm": OrangeRecorder,
    }
    monkeypatch.setattr(cli, "PORTAL_RUNNERS", runner_map)
    monkeypatch.setattr(cli, "get_runner", lambda portal_name: runner_map[portal_name])

    exit_code = cli.main(["all", "--dry-run"])

    assert exit_code == 0
    assert order == ["orangehrm", "saucedemo"]


def test_all_with_input_path_is_rejected(monkeypatch, tmp_path, capsys) -> None:
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["all", "--dry-run", "--input", "records.json"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "--input can only be used with one portal" in captured.err


def test_cli_source_does_not_import_playwright_browser_or_page_modules() -> None:
    source = (ROOT / "src/portal_automation/__main__.py").read_text(encoding="utf-8")

    assert "playwright" not in source.lower()
    assert "browser" not in source.lower()
    assert "page" not in source.lower()


def test_cli_source_does_not_import_smtplib() -> None:
    source = (ROOT / "src/portal_automation/__main__.py").read_text(encoding="utf-8")

    assert "smtplib" not in source


def test_cli_source_does_not_contain_demo_credentials() -> None:
    source = (ROOT / "src/portal_automation/__main__.py").read_text(encoding="utf-8")

    assert "secret_sauce" not in source
    assert "admin123" not in source
