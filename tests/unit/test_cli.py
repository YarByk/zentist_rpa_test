from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from portal_automation import __main__ as cli
from portal_automation.core.models import ItemResult, ItemStatus, ReasonCode, RunResult, RunStatus
from portal_automation.core.retries import PortalError
from portal_automation.core.runner import BasePortalRunnerZX

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ConfigStub:
    db_path: str
    artifacts_dir: str
    business_date: str | None = None
    headless: bool = True
    default_timeout_seconds: int = 30
    orangehrm_timeout_seconds: int | None = None
    saucedemo_timeout_seconds: int | None = None
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

    def portal_timeout_seconds(self, portal_name: str) -> int:
        if portal_name == "orangehrm" and self.orangehrm_timeout_seconds is not None:
            return self.orangehrm_timeout_seconds
        if portal_name == "saucedemo" and self.saucedemo_timeout_seconds is not None:
            return self.saucedemo_timeout_seconds
        return self.default_timeout_seconds


class RunnerStub:
    calls = []
    page_objects = []

    def __init__(self, pages_factory=None) -> None:
        self.pages_factory = pages_factory

    def run(self, context):
        self.calls.append(context)
        if self.pages_factory is not None:
            self.page_objects.append(self.pages_factory(context))
        return RunResult(
            run_id=context.run_id,
            portal_name="stub",
            business_date=context.business_date,
            status=RunStatus.SUCCESS,
            results=[],
        )


class OrangeRunnerStub(RunnerStub):
    calls = []
    page_objects = []


class SauceRunnerStub(RunnerStub):
    calls = []
    page_objects = []


class BrowserManagerStub:
    instances = []

    def __init__(self, config, *, timeout_seconds=None) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.entered = False
        self.exited = False
        self.page = object()
        self.session = type("Session", (), {"page": self.page})()
        self.__class__.instances.append(self)

    def __enter__(self):
        self.entered = True
        return self.session

    def __exit__(self, exc_type, exc, tb) -> None:
        self.exited = True


class SaucePagesStub:
    instances = []

    def __init__(self, page, config) -> None:
        self.page = page
        self.config = config
        self.__class__.instances.append(self)


class OrangePagesStub:
    instances = []

    def __init__(self, page, config) -> None:
        self.page = page
        self.config = config
        self.__class__.instances.append(self)


def configure_cli(monkeypatch, tmp_path):
    OrangeRunnerStub.calls = []
    SauceRunnerStub.calls = []
    OrangeRunnerStub.page_objects = []
    SauceRunnerStub.page_objects = []
    BrowserManagerStub.instances = []
    OrangePagesStub.instances = []
    SaucePagesStub.instances = []
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
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
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


def test_dry_run_path_does_not_start_browser_manager(monkeypatch, tmp_path) -> None:
    configure_cli(monkeypatch, tmp_path)

    class FailingBrowserManager:
        def __init__(self, config, **_kwargs) -> None:
            raise AssertionError("browser manager must not start in dry-run")

    monkeypatch.setattr(cli, "BrowserManager", FailingBrowserManager)

    exit_code = cli.main(["orangehrm", "--dry-run"])

    assert exit_code == 0


def test_non_dry_run_saucedemo_creates_browser_and_injects_pages_factory(
    monkeypatch,
    tmp_path,
) -> None:
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "SauceDemoPages", SaucePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def get(self, key: str):
            return "loaded-sauce-secret" if key == "SAUCEDEMO_PASSWORD" else None

        def require(self, key: str):
            if key == "SAUCEDEMO_PASSWORD":
                return "loaded-sauce-secret"
            raise AssertionError(f"unexpected secret lookup: {key}")

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)

    exit_code = cli.main(["saucedemo"])

    assert exit_code == 0
    assert len(BrowserManagerStub.instances) == 1
    assert BrowserManagerStub.instances[0].entered is True
    assert BrowserManagerStub.instances[0].exited is True
    assert len(SaucePagesStub.instances) == 1
    assert SaucePagesStub.instances[0].page is BrowserManagerStub.instances[0].page
    assert SaucePagesStub.instances[0].config is SauceRunnerStub.calls[0].config


def test_non_dry_run_orangehrm_creates_browser_and_injects_pages_factory(
    monkeypatch,
    tmp_path,
) -> None:
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def get(self, key: str):
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            raise AssertionError(f"unexpected secret lookup: {key}")

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)

    exit_code = cli.main(["orangehrm"])

    assert exit_code == 0
    assert len(BrowserManagerStub.instances) == 1
    assert BrowserManagerStub.instances[0].entered is True
    assert BrowserManagerStub.instances[0].exited is True
    assert len(OrangePagesStub.instances) == 1
    assert OrangePagesStub.instances[0].page is BrowserManagerStub.instances[0].page
    assert OrangePagesStub.instances[0].config is OrangeRunnerStub.calls[0].config


def test_all_non_dry_run_uses_separate_browser_sessions_per_portal(monkeypatch, tmp_path) -> None:
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "SauceDemoPages", SaucePagesStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def get(self, key: str):
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            if key == "SAUCEDEMO_PASSWORD":
                return "loaded-sauce-secret"
            return None

        def require(self, key: str):
            value = self.get(key)
            if value is None:
                raise AssertionError(f"unexpected secret lookup: {key}")
            return value

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)

    exit_code = cli.main(["all"])

    assert exit_code == 0
    assert len(BrowserManagerStub.instances) == 2
    assert all(instance.entered and instance.exited for instance in BrowserManagerStub.instances)
    assert BrowserManagerStub.instances[0].page is not BrowserManagerStub.instances[1].page
    assert {page.page for page in SaucePagesStub.instances + OrangePagesStub.instances} == {
        instance.page for instance in BrowserManagerStub.instances
    }


def test_non_dry_run_passes_resolved_orangehrm_timeout_to_browser_manager(
    monkeypatch,
    tmp_path,
) -> None:
    config = configure_cli(monkeypatch, tmp_path)
    config.orangehrm_timeout_seconds = 45
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def get(self, key: str):
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            value = self.get(key)
            if value is None:
                raise AssertionError(f"unexpected secret lookup: {key}")
            return value

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)

    exit_code = cli.main(["orangehrm"])

    assert exit_code == 0
    assert len(BrowserManagerStub.instances) == 1
    assert BrowserManagerStub.instances[0].timeout_seconds == 45


def test_non_dry_run_passes_resolved_saucedemo_timeout_to_browser_manager(
    monkeypatch,
    tmp_path,
) -> None:
    config = configure_cli(monkeypatch, tmp_path)
    config.saucedemo_timeout_seconds = 12
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "SauceDemoPages", SaucePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def get(self, key: str):
            return "loaded-sauce-secret" if key == "SAUCEDEMO_PASSWORD" else None

        def require(self, key: str):
            value = self.get(key)
            if value is None:
                raise AssertionError(f"unexpected secret lookup: {key}")
            return value

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)

    exit_code = cli.main(["saucedemo"])

    assert exit_code == 0
    assert len(BrowserManagerStub.instances) == 1
    assert BrowserManagerStub.instances[0].timeout_seconds == 12


def test_all_non_dry_run_resolves_timeout_per_portal(monkeypatch, tmp_path) -> None:
    config = configure_cli(monkeypatch, tmp_path)
    config.orangehrm_timeout_seconds = 45
    config.saucedemo_timeout_seconds = 12
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "SauceDemoPages", SaucePagesStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def get(self, key: str):
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            if key == "SAUCEDEMO_PASSWORD":
                return "loaded-sauce-secret"
            return None

        def require(self, key: str):
            value = self.get(key)
            if value is None:
                raise AssertionError(f"unexpected secret lookup: {key}")
            return value

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)

    exit_code = cli.main(["all"])

    assert exit_code == 0
    assert [instance.timeout_seconds for instance in BrowserManagerStub.instances] == [45, 12]


def test_browser_session_closes_after_runner_failure(monkeypatch, tmp_path, capsys) -> None:
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def get(self, key: str):
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            raise AssertionError(f"unexpected secret lookup: {key}")

    class FailingRunner:
        def __init__(self, pages_factory=None) -> None:
            self.pages_factory = pages_factory

        def run(self, context):
            self.pages_factory(context)
            raise RuntimeError("runner failed")

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)
    runner_map = {
        "orangehrm": FailingRunner,
        "saucedemo": SauceRunnerStub,
    }
    monkeypatch.setattr(cli, "PORTAL_RUNNERS", runner_map)
    monkeypatch.setattr(cli, "get_runner", lambda portal_name: runner_map[portal_name])

    exit_code = cli.main(["orangehrm"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "runner failed" in captured.err
    assert len(BrowserManagerStub.instances) == 1
    assert BrowserManagerStub.instances[0].exited is True


def test_missing_chromium_hint_is_printed_without_traceback(monkeypatch, tmp_path, capsys) -> None:
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def get(self, key: str):
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            raise AssertionError(f"unexpected secret lookup: {key}")

    class FailingBrowserManager:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def __enter__(self):
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "Unable to launch Chromium browser. Install Chromium with: "
                "python -m playwright install chromium",
            )

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)
    monkeypatch.setattr(cli, "BrowserManager", FailingBrowserManager)

    exit_code = cli.main(["orangehrm"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "python -m playwright install chromium" in captured.err
    assert "Traceback" not in captured.err


def test_recover_command_does_not_start_browser(monkeypatch, tmp_path) -> None:
    config = configure_cli(monkeypatch, tmp_path)

    class FailingBrowserManager:
        def __init__(self, config, **_kwargs) -> None:
            raise AssertionError("browser manager must not start for recover")

    config_type = type(
        "ConfigType",
        (),
        {"from_env": classmethod(lambda cls: config)},
    )
    monkeypatch.setattr(cli, "AppConfig", config_type)
    monkeypatch.setattr(cli, "BrowserManager", FailingBrowserManager)

    exit_code = cli.main(["recover", "--business-date", "2026-06-29", "--dry-run"])

    assert exit_code == 0


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


def test_cli_source_uses_shared_browser_manager_without_raw_playwright_imports() -> None:
    source = (ROOT / "src/portal_automation/__main__.py").read_text(encoding="utf-8")

    assert "BrowserManager" in source
    assert "sync_playwright" not in source
    assert "from playwright" not in source.lower()


def test_cli_source_does_not_import_smtplib() -> None:
    source = (ROOT / "src/portal_automation/__main__.py").read_text(encoding="utf-8")

    assert "smtplib" not in source


def test_cli_source_does_not_contain_demo_credentials() -> None:
    source = (ROOT / "src/portal_automation/__main__.py").read_text(encoding="utf-8")

    assert "secret_sauce" not in source
    assert "admin123" not in source


class CliArtifactRunner(BasePortalRunnerZX):
    portal_name = "orangehrm"
    operation_name = "cli_artifact_check"

    def __init__(self, pages_factory=None) -> None:
        self.pages_factory = pages_factory

    def preflight_check(self, context):
        return None

    def load_items(self, context):
        return [{"item_key": "cli-item"}]

    def process_item(self, context, item):
        assert self.pages_factory is not None
        self.pages_factory(context)
        return ItemResult(
            item_key="cli-item",
            operation=self.operation_name,
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            details={"note": "safe artifact test"},
        )

    def finalize(self, context, result):
        report_path = context.reporter.write_report(result)
        context.email.send_report(
            run_id=context.run_id,
            to=None,
            subject=f"CLI artifact report: {context.run_id}",
            body=context.reporter.render(result),
            report_path=report_path,
        )


def test_non_dry_run_cli_prints_summary_and_creates_artifact_shape_without_real_browser(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            self.config = config

        def get(self, key: str):
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            raise AssertionError(f"unexpected secret lookup: {key}")

    runner_map = {"orangehrm": CliArtifactRunner, "saucedemo": SauceRunnerStub}
    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)
    monkeypatch.setattr(cli, "PORTAL_RUNNERS", runner_map)
    monkeypatch.setattr(cli, "get_runner", lambda portal_name: runner_map[portal_name])

    exit_code = cli.main(["orangehrm"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "run_summary portal=orangehrm" in captured.out
    assert "report_path=" in captured.out
    assert "artifacts_dir=" in captured.out
    assert "email_backend=dry_run" in captured.out
    assert "email_artifact=" in captured.out
    assert "loaded-orange-secret" not in captured.out

    run_dirs = list((tmp_path / "artifacts" / "runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "report.txt").is_file()
    assert (run_dir / "email_report.txt").is_file()
    assert (run_dir / "events.jsonl").is_file()
    assert (run_dir / "metrics.json").is_file()
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            run_dir / "report.txt",
            run_dir / "email_report.txt",
            run_dir / "events.jsonl",
            run_dir / "metrics.json",
        ]
    )
    assert "item_key=cli-item" in combined
    assert "loaded-orange-secret" not in combined
    assert "secret_sauce" not in combined
