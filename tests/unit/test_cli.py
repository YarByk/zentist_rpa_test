from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from portal_automation import __main__ as cli
from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import (
    ItemResult,
    ItemStatus,
    ReasonCode,
    RunResult,
    RunStatus,
)
from portal_automation.core.retries import PortalError
from portal_automation.core.runner import BasePortalRunnerZX

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ConfigStub:
    # Minimal runtime config used to drive CLI behavior in isolation.
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
        """Portal timeout seconds.

        Args:
            portal_name: Value supplied by the test or fixture for `portal_name`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        if portal_name == "orangehrm" and self.orangehrm_timeout_seconds is not None:
            return self.orangehrm_timeout_seconds
        if portal_name == "saucedemo" and self.saucedemo_timeout_seconds is not None:
            return self.saucedemo_timeout_seconds
        return self.default_timeout_seconds


class RunnerStub:
    # Captures each run context and optional page-object creation requested by the CLI.
    calls = []
    page_objects = []

    def __init__(self, pages_factory=None) -> None:
        """Initialize this test helper instance.

        Args:
            pages_factory: Value supplied by the test or fixture for `pages_factory`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.pages_factory = pages_factory

    def run(self, context):
        """Run.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
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
    # Lightweight context manager used to assert when the CLI does or does not open UI automation.
    instances = []

    def __init__(self, config, *, timeout_seconds=None) -> None:
        """Initialize this test helper instance.

        Args:
            config: Value supplied by the test or fixture for `config`.
            timeout_seconds: Value supplied by the test or fixture for `timeout_seconds`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.config = config
        self.timeout_seconds = timeout_seconds
        self.entered = False
        self.exited = False
        self.page = object()
        self.visible_results: list[tuple[str, str]] = []
        self.session = type("Session", (), {"page": self.page, "diagnostics": self})()
        self.__class__.instances.append(self)

    def __enter__(self):
        """Enter.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.entered = True
        return self.session

    def __exit__(self, exc_type, exc, tb) -> None:
        """Exit.

        Args:
            exc_type: Value supplied by the test or fixture for `exc_type`.
            exc: Value supplied by the test or fixture for `exc`.
            tb: Value supplied by the test or fixture for `tb`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.exited = True

    def pause_for_visible_result(self, title: str, detail: str) -> None:
        """Capture a headed-browser result page request."""
        self.visible_results.append((title, detail))


class SaucePagesStub:
    # Records the page/config pair passed to the SauceDemo page factory branch.
    instances = []

    def __init__(self, page, config) -> None:
        """Initialize this test helper instance.

        Args:
            page: Value supplied by the test or fixture for `page`.
            config: Value supplied by the test or fixture for `config`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page = page
        self.config = config
        self.__class__.instances.append(self)


class OrangePagesStub:
    # Records the page/config pair passed to the OrangeHRM page factory branch.
    instances = []

    def __init__(self, page, config) -> None:
        """Initialize this test helper instance.

        Args:
            page: Value supplied by the test or fixture for `page`.
            config: Value supplied by the test or fixture for `config`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.page = page
        self.config = config
        self.__class__.instances.append(self)


def configure_cli(monkeypatch, tmp_path):
    # Centralized test wiring so each CLI test starts from a clean stubbed environment.
    """Configure cli.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that top level help exits zero.

    Args:
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    exit_code = cli.main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage:" in captured.out


@pytest.mark.parametrize("portal_name", ["orangehrm", "saucedemo", "all", "recover"])
def test_subcommand_help_exits_zero(portal_name, capsys) -> None:
    """Verify that subcommand help exits zero.

    Args:
        portal_name: Value supplied by the test or fixture for `portal_name`.
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    exit_code = cli.main([portal_name, "--help"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "usage:" in captured.out


def test_unknown_portal_exits_nonzero_and_lists_available_portals(capsys) -> None:
    """Verify that unknown portal exits nonzero and lists available portals.

    Args:
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    exit_code = cli.main(["unknown"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "orangehrm" in captured.err
    assert "saucedemo" in captured.err
    assert "all" in captured.err


def test_business_date_argument_is_parsed_into_date(monkeypatch, tmp_path) -> None:
    """Verify that business date argument is parsed into date.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm", "--dry-run", "--business-date", "2026-06-29"])

    assert exit_code == 0
    assert OrangeRunnerStub.calls[0].business_date == date(2026, 6, 29)


def test_invalid_business_date_exits_nonzero(capsys) -> None:
    """Verify that invalid business date exits nonzero.

    Args:
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    exit_code = cli.main(["orangehrm", "--business-date", "06-29-2026"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "YYYY-MM-DD" in captured.err


def test_headless_argument_overrides_config(monkeypatch, tmp_path) -> None:
    """Verify that headless argument overrides config.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    config = configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm", "--dry-run", "--headless", "false"])

    assert exit_code == 0
    assert config.headless is True
    assert OrangeRunnerStub.calls[0].config.headless is False


def test_email_backend_argument_overrides_config(monkeypatch, tmp_path) -> None:
    """Verify that email backend argument overrides config.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    config = configure_cli(monkeypatch, tmp_path)
    config.smtp_host = "smtp.example.com"
    config.smtp_from = "reports@example.com"
    config.report_email_to = "reviewer@example.com"

    exit_code = cli.main(["orangehrm", "--dry-run", "--email-backend", "smtp"])

    assert exit_code == 0
    assert OrangeRunnerStub.calls[0].config.email_backend == "smtp"


def test_smtp_backend_missing_required_config_fails_fast(monkeypatch, tmp_path, capsys) -> None:
    """Verify that smtp backend missing required config fails fast.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    config = configure_cli(monkeypatch, tmp_path)
    config.email_backend = "smtp"

    exit_code = cli.main(["orangehrm", "--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "SMTP backend is selected" in captured.err


def test_single_portal_run_uses_only_selected_registry_runner(monkeypatch, tmp_path) -> None:
    """Verify that single portal run uses only selected registry runner.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm", "--dry-run"])

    assert exit_code == 0
    assert len(OrangeRunnerStub.calls) == 1
    assert SauceRunnerStub.calls == []


def test_runtime_path_uses_secrets_loader_for_selected_portal(monkeypatch, tmp_path) -> None:
    # Real runs must pull portal secrets through the dedicated loader instead of hardcoding them.
    """Verify that runtime path uses secrets loader for selected portal.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            calls.append(("get", key))
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            return None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    """Verify that dry run path does not start browser manager.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)

    class FailingBrowserManager:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            raise AssertionError("browser manager must not start in dry-run")

    monkeypatch.setattr(cli, "BrowserManager", FailingBrowserManager)

    exit_code = cli.main(["orangehrm", "--dry-run"])

    assert exit_code == 0


def test_non_dry_run_saucedemo_creates_browser_and_injects_pages_factory(
    monkeypatch,
    tmp_path,
) -> None:
    """Verify that non dry run saucedemo creates browser and injects pages factory.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "SauceDemoPages", SaucePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return "loaded-sauce-secret" if key == "SAUCEDEMO_PASSWORD" else None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    """Verify that non dry run orangehrm creates browser and injects pages factory.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    """Verify that all non dry run uses separate browser sessions per portal.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "SauceDemoPages", SaucePagesStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            if key == "SAUCEDEMO_PASSWORD":
                return "loaded-sauce-secret"
            return None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    """Verify that non dry run passes resolved orangehrm timeout to browser manager.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    config = configure_cli(monkeypatch, tmp_path)
    config.orangehrm_timeout_seconds = 45
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    """Verify that non dry run passes resolved saucedemo timeout to browser manager.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    config = configure_cli(monkeypatch, tmp_path)
    config.saucedemo_timeout_seconds = 12
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "SauceDemoPages", SaucePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return "loaded-sauce-secret" if key == "SAUCEDEMO_PASSWORD" else None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    """Verify that all non dry run resolves timeout per portal.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    config = configure_cli(monkeypatch, tmp_path)
    config.orangehrm_timeout_seconds = 45
    config.saucedemo_timeout_seconds = 12
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "SauceDemoPages", SaucePagesStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            if key == "SAUCEDEMO_PASSWORD":
                return "loaded-sauce-secret"
            return None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            value = self.get(key)
            if value is None:
                raise AssertionError(f"unexpected secret lookup: {key}")
            return value

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)

    exit_code = cli.main(["all"])

    assert exit_code == 0
    assert [instance.timeout_seconds for instance in BrowserManagerStub.instances] == [45, 12]


def test_browser_session_closes_after_runner_failure(monkeypatch, tmp_path, capsys) -> None:
    """Verify that browser session closes after runner failure.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            raise AssertionError(f"unexpected secret lookup: {key}")

    class FailingRunner:
        def __init__(self, pages_factory=None) -> None:
            """Initialize this test helper instance.

            Args:
                pages_factory: Value supplied by the test or fixture for `pages_factory`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.pages_factory = pages_factory

        def run(self, context):
            """Run.

            Args:
                context: Value supplied by the test or fixture for `context`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    """Verify that missing chromium hint is printed without traceback.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            if key == "ORANGEHRM_PASSWORD":
                return "loaded-orange-secret"
            raise AssertionError(f"unexpected secret lookup: {key}")

    class FailingBrowserManager:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def __enter__(self):
            """Enter.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "Unable to launch Chromium browser. Install Chromium with: "
                "python -m playwright install chromium",
            )

        def __exit__(self, exc_type, exc, tb) -> None:
            """Exit.

            Args:
                exc_type: Value supplied by the test or fixture for `exc_type`.
                exc: Value supplied by the test or fixture for `exc`.
                tb: Value supplied by the test or fixture for `tb`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return None

    monkeypatch.setattr(cli, "SecretsLoader", LoaderStub)
    monkeypatch.setattr(cli, "BrowserManager", FailingBrowserManager)

    exit_code = cli.main(["orangehrm"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "python -m playwright install chromium" in captured.err
    assert "Traceback" not in captured.err


def test_recover_command_does_not_start_browser(monkeypatch, tmp_path) -> None:
    """Verify that recover command does not start browser.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    config = configure_cli(monkeypatch, tmp_path)

    class FailingBrowserManager:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    """Verify that non dry run missing selected portal secret fails fast.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["orangehrm"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "ORANGEHRM_PASSWORD is required for this runtime path." in captured.err


def test_all_executes_both_portals_in_sorted_order(monkeypatch, tmp_path) -> None:
    """Verify that all executes both portals in sorted order.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    order = []
    configure_cli(monkeypatch, tmp_path)

    class OrangeRecorder(OrangeRunnerStub):
        def run(self, context):
            """Run.

            Args:
                context: Value supplied by the test or fixture for `context`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            order.append("orangehrm")
            return super().run(context)

    class SauceRecorder(SauceRunnerStub):
        def run(self, context):
            """Run.

            Args:
                context: Value supplied by the test or fixture for `context`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    """Verify that all with input path is rejected.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)

    exit_code = cli.main(["all", "--dry-run", "--input", "records.json"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "--input can only be used with one portal" in captured.err


def test_cli_source_uses_shared_browser_manager_without_raw_playwright_imports() -> None:
    """Verify that cli source uses shared browser manager without raw playwright imports.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/__main__.py").read_text(encoding="utf-8")

    assert "BrowserManager" in source
    assert "sync_playwright" not in source
    assert "from playwright" not in source.lower()


def test_cli_source_does_not_import_smtplib() -> None:
    """Verify that cli source does not import smtplib.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/__main__.py").read_text(encoding="utf-8")

    assert "smtplib" not in source


def test_cli_source_does_not_contain_demo_credentials() -> None:
    """Verify that cli source does not contain demo credentials.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/__main__.py").read_text(encoding="utf-8")

    assert "secret_sauce" not in source
    assert "admin123" not in source


class CliArtifactRunner(BasePortalRunnerZX):
    portal_name = "orangehrm"
    operation_name = "cli_artifact_check"

    def __init__(self, pages_factory=None) -> None:
        """Initialize this test helper instance.

        Args:
            pages_factory: Value supplied by the test or fixture for `pages_factory`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.pages_factory = pages_factory

    def preflight_check(self, context):
        """Preflight check.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return None

    def load_items(self, context):
        """Load items.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return [{"item_key": "cli-item"}]

    def process_item(self, context, item):
        """Process item.

        Args:
            context: Value supplied by the test or fixture for `context`.
            item: Value supplied by the test or fixture for `item`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
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
        """Finalize.

        Args:
            context: Value supplied by the test or fixture for `context`.
            result: Value supplied by the test or fixture for `result`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
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
    """Verify that non dry run cli prints summary and creates artifact shape without real browser.

    Args:
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        capsys: Value supplied by the test or fixture for `capsys`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    configure_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "BrowserManager", BrowserManagerStub)
    monkeypatch.setattr(cli, "OrangeHrmPages", OrangePagesStub)

    class LoaderStub:
        def __init__(self, config, **_kwargs) -> None:
            """Initialize this test helper instance.

            Args:
                config: Value supplied by the test or fixture for `config`.
                **_kwargs: Value supplied by the test or fixture for `_kwargs`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self.config = config

        def get(self, key: str):
            """Get.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return "loaded-orange-secret" if key == "ORANGEHRM_PASSWORD" else None

        def require(self, key: str):
            """Require.

            Args:
                key: Value supplied by the test or fixture for `key`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
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
    assert "Run details (execution order):" in captured.out
    assert "1. cli-item - success" in captured.out
    assert "Machine-readable details:" in captured.out
    assert "run_summary portal=orangehrm" in captured.out
    assert "run_item portal=orangehrm" in captured.out
    assert "item_key=cli-item" in captured.out
    assert "operation=cli_artifact_check" in captured.out
    assert "status=success" in captured.out
    assert "attempts=1" in captured.out
    assert "run_result portal=orangehrm" in captured.out
    assert "Status: success." in captured.out
    assert "1 succeeded, 0 failed, 0 skipped" in captured.out
    assert captured.out.index("run_item portal=orangehrm") < captured.out.index(
        "run_result portal=orangehrm"
    )
    assert captured.out.index("Run details (execution order):") < captured.out.index(
        "Machine-readable details:"
    )
    assert captured.out.index("Machine-readable details:") < captured.out.index(
        "run_item portal=orangehrm"
    )
    assert "report_path=" in captured.out
    assert "artifacts_dir=" in captured.out
    assert "email_backend=dry_run" in captured.out
    assert "email_artifact=" in captured.out
    assert "loaded-orange-secret" not in captured.out
    assert BrowserManagerStub.instances[0].visible_results
    visible_title, visible_detail = BrowserManagerStub.instances[0].visible_results[-1]
    assert visible_title == "orangehrm run finished with success"
    assert "Status: success." in visible_detail
    assert "Run details (execution order):" in visible_detail
    assert "1. cli-item - success" in visible_detail

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


def test_human_item_summary_includes_saucedemo_order_details_without_secret() -> None:
    """Verify that operator console summary includes safe Sauce Demo order details only.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If safe details are missing or secret-like details leak.
    """
    item = ItemResult(
        item_key="standard_user",
        operation="checkout",
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
        details={
            "cart_count": 3,
            "item_names": ["Sauce Labs Backpack", "Sauce Labs Bike Light"],
            "password": "must-not-leak",
            "total": "Total: $43.18",
        },
    )

    detail = cli._human_item_summary(item)

    assert "- standard_user - success" in detail
    assert "Checkout: 3 product(s), Total: $43.18" in detail
    assert "Products: Sauce Labs Backpack, Sauce Labs Bike Light" in detail
    assert "must-not-leak" not in detail


def test_visible_result_detail_includes_saucedemo_products(tmp_path: Path) -> None:
    """Verify that headed Sauce Demo completion page lists completed products.

    Args:
        tmp_path: Temporary directory supplied by pytest.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If the visible result omits safe item details or leaks secrets.
    """
    artifacts = ArtifactStore(tmp_path / "artifacts")
    context = SimpleNamespace(run_id="run-sauce", artifacts=artifacts)
    result = RunResult(
        run_id="run-sauce",
        portal_name="saucedemo",
        business_date=date(2026, 7, 17),
        status=RunStatus.SUCCESS,
        results=[
            ItemResult(
                item_key="standard_user",
                operation="checkout",
                status=ItemStatus.SUCCESS,
                reason_code=None,
                error_detail=None,
                artifact_path=None,
                details={
                    "cart_count": 3,
                    "item_names": [
                        "Sauce Labs Backpack",
                        "Sauce Labs Bike Light",
                        "Sauce Labs Bolt T-Shirt",
                    ],
                    "password": "must-not-leak",
                    "total": "Total: $60.45",
                },
            )
        ],
    )

    detail = cli._run_visible_result_detail(context, result)

    assert "Status: success. Completed 1 item(s): 1 succeeded, 0 failed, 0 skipped." in detail
    assert "Run details (execution order):" in detail
    assert "1. standard_user - success" in detail
    assert "Checkout: 3 product(s), Total: $60.45" in detail
    assert (
        "Products: Sauce Labs Backpack, Sauce Labs Bike Light, Sauce Labs Bolt T-Shirt"
    ) in detail
    assert "must-not-leak" not in detail
