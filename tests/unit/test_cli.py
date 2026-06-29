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
    email_backend: str = "dry_run"
    stale_item_timeout_seconds: int = 300
    orangehrm_input_path: str = "data/orangehrm_employees.json"
    saucedemo_input_path: str = "data/saucedemo_accounts.json"


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


@pytest.mark.parametrize("portal_name", ["orangehrm", "saucedemo", "all"])
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
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm", "--dry-run", "--email-backend", "smtp"])

    assert exit_code == 0
    assert OrangeRunnerStub.calls[0].config.email_backend == "smtp"


def test_single_portal_run_uses_only_selected_registry_runner(monkeypatch, tmp_path) -> None:
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm", "--dry-run"])

    assert exit_code == 0
    assert len(OrangeRunnerStub.calls) == 1
    assert SauceRunnerStub.calls == []


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
