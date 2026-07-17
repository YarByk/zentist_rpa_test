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
    # Enough config for registered runners to load input during dry-run checks.
    orangehrm_input_path = str(ROOT / "data/orangehrm_employees.json")
    orangehrm_password = None
    saucedemo_input_path = str(ROOT / "data/saucedemo_accounts.json")
    saucedemo_password = "pw"


class FakePersistence:
    # Records lifecycle calls so dry-run registry tests can prove no real item methods run.
    def __init__(self) -> None:
        """Initialize this test helper instance.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.created_runs: list[tuple[str, str, date]] = []
        self.finished_runs: list[tuple[str, RunStatus, dict[str, int]]] = []
        self.touched_real_run_methods: list[str] = []

    def create_run(self, run_id: str, portal_name: str, business_date: date) -> None:
        """Create run.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.created_runs.append((run_id, portal_name, business_date))

    def finish_run(self, run_id: str, status: RunStatus, summary: dict[str, int]) -> None:
        """Finish run.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            status: Value supplied by the test or fixture for `status`.
            summary: Value supplied by the test or fixture for `summary`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.finished_runs.append((run_id, status, summary))

    def get_committed_items(self, portal_name: str, business_date: date) -> set[str]:
        """Get committed items.

        Args:
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
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
        """Mark item in progress.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.
            item_key: Value supplied by the test or fixture for `item_key`.
            operation: Value supplied by the test or fixture for `operation`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.touched_real_run_methods.append("mark_item_in_progress")

    def upsert_item_result(self, *args: object) -> None:
        """Upsert item result.

        Args:
            *args: Value supplied by the test or fixture for `args`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.touched_real_run_methods.append("upsert_item_result")

    def list_results_by_business_date(self, portal_name: str, business_date: date) -> list[object]:
        """List results by business date.

        Args:
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.touched_real_run_methods.append("list_results_by_business_date")
        return []


def make_context(persistence: FakePersistence) -> RunContext:
    # Build a minimal dry-run context shared by both registered runner classes.
    """Make context.

    Args:
        persistence: Value supplied by the test or fixture for `persistence`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that portal runners registry keys match contract.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert set(PORTAL_RUNNERS) == {"orangehrm", "saucedemo"}


def test_get_runner_resolves_orangehrm_and_saucedemo() -> None:
    """Verify that get runner resolves orangehrm and saucedemo.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert get_runner("orangehrm") is OrangeHrmRunner
    assert get_runner("saucedemo") is SauceDemoRunner


def test_unknown_portal_error_lists_requested_and_available_portals() -> None:
    """Verify that unknown portal error lists requested and available portals.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    with pytest.raises(ValueError) as exc_info:
        get_runner("unknown")

    message = str(exc_info.value)
    assert "unknown" in message
    assert "orangehrm" in message
    assert "saucedemo" in message


def test_registered_runner_classes_subclass_base_runner_and_do_not_override_run() -> None:
    # Portal implementations must keep the shared lifecycle in BasePortalRunnerZX.
    """Verify that registered runner classes subclass base runner and do not override run.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    for runner_class in PORTAL_RUNNERS.values():
        assert issubclass(runner_class, BasePortalRunnerZX)
        assert "run" not in runner_class.__dict__
        assert runner_class.run is BasePortalRunnerZX.run


def test_minimal_runner_contract_attributes_match_frozen_names() -> None:
    """Verify that minimal runner contract attributes match frozen names.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert OrangeHrmRunner.portal_name == "orangehrm"
    assert OrangeHrmRunner.operation_name == "sync_employee_state"
    assert SauceDemoRunner.portal_name == "saucedemo"
    assert SauceDemoRunner.operation_name == "checkout"


@pytest.mark.parametrize("runner_class", [OrangeHrmRunner, SauceDemoRunner])
def test_minimal_runners_can_run_safely_in_dry_run(
    runner_class: type[BasePortalRunnerZX],
) -> None:
    """Verify that minimal runners can run safely in dry run.

    Args:
        runner_class: Value supplied by the test or fixture for `runner_class`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    persistence = FakePersistence()
    result = runner_class().run(make_context(persistence))

    assert result == RunResult(
        run_id="run-1",
        portal_name=runner_class.portal_name,
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )
    assert persistence.created_runs == [("run-1", runner_class.portal_name, date(2026, 6, 29))]
    assert persistence.finished_runs == [
        (
            "run-1",
            RunStatus.SUCCESS,
            {"total": 0, "success": 0, "failed": 0, "skipped": 0},
        )
    ]
    assert persistence.touched_real_run_methods == []


def test_core_registry_is_only_core_module_importing_concrete_portal_runners() -> None:
    # The registry is the single intentional dependency from core into portal implementations.
    """Verify that core registry is only core module importing concrete portal runners.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    offenders = []
    for path in (ROOT / "src/portal_automation/core").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "portal_automation.portals." in text and path.name != "registry.py":
            offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_core_registry_has_no_scattered_if_dispatch() -> None:
    """Verify that core registry has no scattered if dispatch.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    registry = (ROOT / "src/portal_automation/core/registry.py").read_text(encoding="utf-8")

    assert "if portal_name" not in registry
    assert "elif" not in registry


def test_new_registry_and_runner_files_do_not_reference_browser_automation_symbols() -> None:
    """Verify that new registry and runner files do not reference browser automation symbols.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
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
    """Verify that forbidden modules were not created.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
