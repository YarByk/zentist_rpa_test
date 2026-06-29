from datetime import date
from pathlib import Path

import pytest

from portal_automation.core.models import RunContext, RunResult, RunStatus
from portal_automation.core.registry import PORTAL_RUNNERS, get_runner
from portal_automation.core.runner import BasePortalRunnerZX
from portal_automation.portals.orangehrm.runner import OrangeHrmRunner
from portal_automation.portals.saucedemo.runner import SauceDemoRunner

ROOT = Path(__file__).resolve().parents[2]


class ConfigStub:
    orangehrm_input_path = str(ROOT / "data/orangehrm_employees.json")
    orangehrm_password = None
    saucedemo_input_path = str(ROOT / "data/saucedemo_accounts.json")
    saucedemo_password = "pw"


class FakePersistence:
    def __init__(self) -> None:
        self.created_runs: list[tuple[str, str, date]] = []
        self.finished_runs: list[tuple[str, RunStatus, dict[str, int]]] = []
        self.touched_real_run_methods: list[str] = []

    def create_run(self, run_id: str, portal_name: str, business_date: date) -> None:
        self.created_runs.append((run_id, portal_name, business_date))

    def finish_run(self, run_id: str, status: RunStatus, summary: dict[str, int]) -> None:
        self.finished_runs.append((run_id, status, summary))

    def get_committed_items(self, portal_name: str, business_date: date) -> set[str]:
        self.touched_real_run_methods.append("get_committed_items")
        return set()

    def mark_item_in_progress(
        self,
        run_id: str,
        portal_name: str,
        business_date: date,
        item_key: str,
        operation: str,
    ) -> None:
        self.touched_real_run_methods.append("mark_item_in_progress")

    def upsert_item_result(self, *args: object) -> None:
        self.touched_real_run_methods.append("upsert_item_result")

    def list_results_by_business_date(self, portal_name: str, business_date: date) -> list[object]:
        self.touched_real_run_methods.append("list_results_by_business_date")
        return []


def make_context(persistence: FakePersistence) -> RunContext:
    return RunContext(
        run_id="run-1",
        business_date=date(2026, 6, 29),
        dry_run=True,
        stale_item_timeout_seconds=300,
        config=ConfigStub(),
        persistence=persistence,
        reporter={},
        logger={},
        metrics={},
        artifacts={},
        email={},
    )


def test_portal_runners_registry_keys_match_contract() -> None:
    assert set(PORTAL_RUNNERS) == {"orangehrm", "saucedemo"}


def test_get_runner_resolves_orangehrm_and_saucedemo() -> None:
    assert get_runner("orangehrm") is OrangeHrmRunner
    assert get_runner("saucedemo") is SauceDemoRunner


def test_unknown_portal_error_lists_requested_and_available_portals() -> None:
    with pytest.raises(ValueError) as exc_info:
        get_runner("unknown")

    message = str(exc_info.value)
    assert "unknown" in message
    assert "orangehrm" in message
    assert "saucedemo" in message


def test_registered_runner_classes_subclass_base_runner_and_do_not_override_run() -> None:
    for runner_class in PORTAL_RUNNERS.values():
        assert issubclass(runner_class, BasePortalRunnerZX)
        assert "run" not in runner_class.__dict__
        assert runner_class.run is BasePortalRunnerZX.run


def test_minimal_runner_contract_attributes_match_frozen_names() -> None:
    assert OrangeHrmRunner.portal_name == "orangehrm"
    assert OrangeHrmRunner.operation_name == "sync_employee_state"
    assert OrangeHrmRunner.max_sessions_per_login == 1
    assert SauceDemoRunner.portal_name == "saucedemo"
    assert SauceDemoRunner.operation_name == "checkout"
    assert SauceDemoRunner.max_sessions_per_account == 1


@pytest.mark.parametrize("runner_class", [OrangeHrmRunner, SauceDemoRunner])
def test_minimal_runners_can_run_safely_in_dry_run(
    runner_class: type[BasePortalRunnerZX],
) -> None:
    persistence = FakePersistence()
    result = runner_class().run(make_context(persistence))

    assert result == RunResult(
        run_id="run-1",
        portal_name=runner_class.portal_name,
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )
    assert persistence.created_runs == [
        ("run-1", runner_class.portal_name, date(2026, 6, 29))
    ]
    assert persistence.finished_runs == [
        (
            "run-1",
            RunStatus.SUCCESS,
            {"total": 0, "success": 0, "failed": 0, "skipped": 0},
        )
    ]
    assert persistence.touched_real_run_methods == []


def test_core_registry_is_only_core_module_importing_concrete_portal_runners() -> None:
    offenders = []
    for path in (ROOT / "src/portal_automation/core").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "portal_automation.portals." in text and path.name != "registry.py":
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_core_registry_has_no_scattered_if_dispatch() -> None:
    registry = (ROOT / "src/portal_automation/core/registry.py").read_text(encoding="utf-8")

    assert "if portal_name" not in registry
    assert "elif" not in registry


def test_new_registry_and_runner_files_do_not_reference_browser_automation_symbols() -> None:
    files = [
        ROOT / "src/portal_automation/core/registry.py",
        ROOT / "src/portal_automation/portals/orangehrm/runner.py",
        ROOT / "src/portal_automation/portals/saucedemo/runner.py",
    ]
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}: {symbol}"
        for path in files
        for text in [path.read_text(encoding="utf-8").lower()]
        for symbol in (
            "import playwright",
            "from playwright",
            "sync_playwright",
            "async_playwright",
            "chromium.launch",
            "firefox.launch",
            "webkit.launch",
        )
        if symbol in text
    ]

    assert offenders == []


def test_forbidden_modules_were_not_created() -> None:
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
