from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from portal_automation.core.models import (
    ItemResult,
    ItemStatus,
    ReasonCode,
    RunContext,
    RunResult,
    RunStatus,
)
from portal_automation.core.retries import PortalError
from portal_automation.core.runner import BasePortalRunnerZX

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class ObjectItem:
    # Tiny helper object used to prove item_key() supports attribute-based access.
    item_key: str


class FakeLogger:
    # Records info/error calls so tests can assert exactly what was logged.
    def __init__(self) -> None:
        """Initialize this test helper instance.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.errors: list[tuple[str, dict[str, str]]] = []
        self.infos: list[tuple[str, dict[str, str]]] = []

    def info(self, event: str, **kwargs: str) -> None:
        """Info.
        
        Args:
            event: Value supplied by the test or fixture for `event`.
            **kwargs: Value supplied by the test or fixture for `kwargs`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.infos.append((event, kwargs))

    def error(self, event: str, **kwargs: str) -> None:
        """Error.
        
        Args:
            event: Value supplied by the test or fixture for `event`.
            **kwargs: Value supplied by the test or fixture for `kwargs`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.errors.append((event, kwargs))


class DiagnosticsStub:
    # Simulates diagnostic artifact capture without touching the real filesystem.
    def __init__(self, *, error: Exception | None = None) -> None:
        """Initialize this test helper instance.
        
        Args:
            error: Value supplied by the test or fixture for `error`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def capture_failure_artifacts(
        self,
        *,
        run_id: str,
        portal_name: str,
        item_key: str,
        artifacts: Any,
    ) -> dict[str, str]:
        """Capture failure artifacts.
        
        Args:
            run_id: Value supplied by the test or fixture for `run_id`.
            portal_name: Value supplied by the test or fixture for `portal_name`.
            item_key: Value supplied by the test or fixture for `item_key`.
            artifacts: Value supplied by the test or fixture for `artifacts`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.calls.append(
            {
                "run_id": run_id,
                "portal_name": portal_name,
                "item_key": item_key,
                "artifacts": artifacts,
            }
        )
        if self.error is not None:
            raise self.error
        return {
            "screenshot_path": f"/artifacts/{portal_name}/{item_key}_failure.png",
            "trace_path": f"/artifacts/{portal_name}/{item_key}_trace.zip",
        }


class FakePersistence:
    # -------------------------------------------------------------------------
    # In-memory stand-in for the run state connector.
    # Each method appends to the shared event list so tests can assert ordering
    # and verify which lifecycle steps happen before others.
    # -------------------------------------------------------------------------
    def __init__(
        self,
        events: list[str],
        committed_items: set[str] | None = None,
        existing_results: list[ItemResult] | None = None,
        fail_on_mark: bool = False,
        fail_on_upsert: bool = False,
    ) -> None:
        """Initialize this test helper instance.
        
        Args:
            events: Value supplied by the test or fixture for `events`.
            committed_items: Value supplied by the test or fixture for `committed_items`.
            existing_results: Value supplied by the test or fixture for `existing_results`.
            fail_on_mark: Value supplied by the test or fixture for `fail_on_mark`.
            fail_on_upsert: Value supplied by the test or fixture for `fail_on_upsert`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.events = events
        self.committed_items = committed_items or set()
        self.results = list(existing_results or [])
        self.current_run_results: list[ItemResult] = []
        self.fail_on_mark = fail_on_mark
        self.fail_on_upsert = fail_on_upsert
        self.finished: tuple[str, RunStatus, dict[str, int]] | None = None

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
        self.events.append(f"create_run:{run_id}:{portal_name}:{business_date.isoformat()}")

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
        self.events.append(f"finish_run:{status.value}")
        self.finished = (run_id, status, summary)

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
        self.events.append(f"mark_item_in_progress:{item_key}")
        if self.fail_on_mark:
            raise RuntimeError("mark failed")

    def upsert_item_result(
        self,
        result: ItemResult,
        run_id: str,
        portal_name: str,
        business_date: date,
    ) -> None:
        """Upsert item result.
        
        Args:
            result: Value supplied by the test or fixture for `result`.
            run_id: Value supplied by the test or fixture for `run_id`.
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.events.append(f"upsert_item_result:{result.item_key}:{result.status.value}")
        if self.fail_on_upsert:
            raise RuntimeError("upsert failed")
        self.results = [old for old in self.results if old.item_key != result.item_key]
        self.results.append(result)
        self.current_run_results = [
            old for old in self.current_run_results if old.item_key != result.item_key
        ]
        self.current_run_results.append(result)

    def list_results_by_business_date(
        self,
        portal_name: str,
        business_date: date,
    ) -> list[ItemResult]:
        """List results by business date.
        
        Args:
            portal_name: Value supplied by the test or fixture for `portal_name`.
            business_date: Value supplied by the test or fixture for `business_date`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.events.append("list_results_by_business_date")
        return list(self.results)

    def list_results_for_run(self, run_id: str) -> list[ItemResult]:
        """List results for one run.

        Args:
            run_id: Value supplied by the test or fixture for `run_id`.

        Returns:
            Persisted item results for this fake run.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.events.append(f"list_results_for_run:{run_id}")
        return list(self.current_run_results)

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
        self.events.append("get_committed_items")
        return set(self.committed_items)


class FakeRunner(BasePortalRunnerZX):
    # Configurable runner used to exercise the shared base lifecycle in isolation.
    portal_name = "fakeportal"
    operation_name = "fake_operation"

    def __init__(
        self,
        items: list[Any],
        behavior: dict[str, str] | None = None,
        load_error: Exception | None = None,
        preflight_error: Exception | None = None,
    ) -> None:
        """Initialize this test helper instance.
        
        Args:
            items: Value supplied by the test or fixture for `items`.
            behavior: Value supplied by the test or fixture for `behavior`.
            load_error: Value supplied by the test or fixture for `load_error`.
            preflight_error: Value supplied by the test or fixture for `preflight_error`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.items = items
        self.behavior = behavior or {}
        self.load_error = load_error
        self.preflight_error = preflight_error
        self.events: list[str] = []
        self.finalized_result: RunResult | None = None

    def preflight_check(self, context: RunContext) -> None:
        """Preflight check.
        
        Args:
            context: Value supplied by the test or fixture for `context`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.events.append("preflight_check")
        context.persistence.events.append("preflight_check")
        if self.preflight_error is not None:
            raise self.preflight_error

    def load_items(self, context: RunContext) -> list[Any]:
        """Load items.
        
        Args:
            context: Value supplied by the test or fixture for `context`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.events.append("load_items")
        context.persistence.events.append("load_items")
        if self.load_error is not None:
            raise self.load_error
        return self.items

    def process_item(self, context: RunContext, item: Any) -> ItemResult:
        """Process item.
        
        Args:
            context: Value supplied by the test or fixture for `context`.
            item: Value supplied by the test or fixture for `item`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        key = self.item_key(item)
        self.events.append(f"process_item:{key}")
        context.persistence.events.append(f"process_item:{key}")
        behavior = self.behavior.get(key, "success")
        if behavior == "portal_error":
            raise PortalError(ReasonCode.PORTAL_TIMEOUT, "temporary failure", attempts=2)
        if behavior == "unexpected":
            raise ValueError("unexpected failure")
        return ItemResult(
            item_key=key,
            operation=self.operation_name,
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            attempts=1,
            details={},
        )

    def finalize(self, context: RunContext, result: RunResult) -> None:
        """Finalize.
        
        Args:
            context: Value supplied by the test or fixture for `context`.
            result: Value supplied by the test or fixture for `result`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self.events.append("finalize")
        context.persistence.events.append(f"finalize:{result.status.value}")
        self.finalized_result = result


def make_context(
    persistence: FakePersistence,
    logger: FakeLogger | None = None,
    dry_run: bool = False,
    diagnostics: DiagnosticsStub | None = None,
) -> RunContext:
    # Build the smallest context object needed to execute the shared runner flow.
    """Make context.
    
    Args:
        persistence: Value supplied by the test or fixture for `persistence`.
        logger: Value supplied by the test or fixture for `logger`.
        dry_run: Value supplied by the test or fixture for `dry_run`.
        diagnostics: Value supplied by the test or fixture for `diagnostics`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = RunContext(
        run_id="run-1",
        business_date=date(2026, 6, 29),
        dry_run=dry_run,
        stale_item_timeout_seconds=300,
        config={},
        persistence=persistence,
        reporter={},
        logger=logger or FakeLogger(),
        metrics={},
        artifacts={},
        email={},
    )
    if diagnostics is not None:
        context.diagnostics = diagnostics
    return context


def test_base_portal_runner_zx_exists_and_run_is_concrete() -> None:
    """Verify that base portal runner zx exists and run is concrete.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert BasePortalRunnerZX.__name__ == "BasePortalRunnerZX"
    assert hasattr(BasePortalRunnerZX, "run")
    assert not getattr(BasePortalRunnerZX.run, "__isabstractmethod__", False)


def test_fake_runner_implements_hooks_and_does_not_override_run() -> None:
    """Verify that fake runner implements hooks and does not override run.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    assert "run" not in FakeRunner.__dict__
    assert FakeRunner.run is BasePortalRunnerZX.run


def test_dry_run_uses_safe_lifecycle_and_returns_empty_success_result() -> None:
    # Dry-run mode should validate the high-level lifecycle without processing items.
    """Verify that dry run uses safe lifecycle and returns empty success result.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    persistence = FakePersistence(events)
    runner = FakeRunner(items=[{"item_key": "a"}])
    context = make_context(persistence, dry_run=True)

    result = runner.run(context)

    assert result == RunResult(
        run_id="run-1",
        portal_name="fakeportal",
        business_date=date(2026, 6, 29),
        status=RunStatus.SUCCESS,
        results=[],
    )
    assert events == [
        "create_run:run-1:fakeportal:2026-06-29",
        "load_items",
        "finalize:success",
        "finish_run:success",
    ]
    assert runner.events == ["load_items", "finalize"]
    assert persistence.finished == (
        "run-1",
        RunStatus.SUCCESS,
        {"total": 0, "success": 0, "failed": 0, "skipped": 0},
    )


def test_load_items_portal_error_finishes_failed_run_and_reraises() -> None:
    """Verify that load items portal error finishes failed run and reraises.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    persistence = FakePersistence(events)
    runner = FakeRunner(
        items=[],
        load_error=PortalError(ReasonCode.INPUT_VALIDATION_FAILED, "bad input"),
    )

    with pytest.raises(PortalError) as error:
        runner.run(make_context(persistence))

    assert error.value.reason is ReasonCode.INPUT_VALIDATION_FAILED
    assert runner.finalized_result is not None
    assert runner.finalized_result.status is RunStatus.FAILED
    assert runner.finalized_result.results[0].item_key == "__load_items__"
    assert runner.finalized_result.results[0].reason_code is ReasonCode.INPUT_VALIDATION_FAILED
    assert events == [
        "create_run:run-1:fakeportal:2026-06-29",
        "load_items",
        "finalize:failed",
        "finish_run:failed",
    ]
    assert persistence.finished == (
        "run-1",
        RunStatus.FAILED,
        {"total": 1, "success": 0, "failed": 1, "skipped": 0},
    )


def test_preflight_portal_error_finishes_failed_run_and_reraises() -> None:
    """Verify that preflight portal error finishes failed run and reraises.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    persistence = FakePersistence(events)
    runner = FakeRunner(
        items=[{"item_key": "a"}],
        preflight_error=PortalError(ReasonCode.CREDENTIAL_EXPIRED, "missing password"),
    )

    with pytest.raises(PortalError) as error:
        runner.run(make_context(persistence))

    assert error.value.reason is ReasonCode.CREDENTIAL_EXPIRED
    assert runner.finalized_result is not None
    assert runner.finalized_result.status is RunStatus.FAILED
    assert runner.finalized_result.results[0].item_key == "__preflight__"
    assert runner.finalized_result.results[0].reason_code is ReasonCode.CREDENTIAL_EXPIRED
    assert events == [
        "create_run:run-1:fakeportal:2026-06-29",
        "load_items",
        "preflight_check",
        "finalize:failed",
        "finish_run:failed",
    ]
    assert "get_committed_items" not in events
    assert not any(event.startswith("mark_item_in_progress") for event in events)


def test_real_run_preflight_and_committed_lookup_happen_before_processing() -> None:
    # The base runner must complete setup checks before touching item execution state.
    """Verify that real run preflight and committed lookup happen before processing.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    persistence = FakePersistence(events)
    runner = FakeRunner(items=[{"item_key": "a"}])

    runner.run(make_context(persistence))

    assert events[:5] == [
        "create_run:run-1:fakeportal:2026-06-29",
        "load_items",
        "preflight_check",
        "get_committed_items",
        "mark_item_in_progress:a",
    ]


def test_committed_items_are_skipped_without_writes_or_processing() -> None:
    """Verify that committed items are skipped without writes or processing.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    committed = ItemResult(
        item_key="a",
        operation="fake_operation",
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
        attempts=1,
        details={},
    )
    events: list[str] = []
    persistence = FakePersistence(events, committed_items={"a"}, existing_results=[committed])
    runner = FakeRunner(items=[{"item_key": "a"}, {"item_key": "b"}])

    result = runner.run(make_context(persistence))

    assert "mark_item_in_progress:a" not in events
    assert "process_item:a" not in events
    assert not any(event == "upsert_item_result:a:skipped" for event in events)
    assert "mark_item_in_progress:b" in events
    assert [item.item_key for item in result.results] == ["a", "b"]


def test_mark_item_in_progress_is_immediately_before_process_item() -> None:
    # Marking in-progress should happen immediately before the business operation starts.
    """Verify that mark item in progress is immediately before process item.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    persistence = FakePersistence(events)
    runner = FakeRunner(items=[{"item_key": "a"}])

    runner.run(make_context(persistence))

    mark_index = events.index("mark_item_in_progress:a")
    assert events[mark_index + 1] == "process_item:a"


def test_successful_item_results_are_persisted_immediately() -> None:
    """Verify that successful item results are persisted immediately.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    persistence = FakePersistence(events)
    runner = FakeRunner(items=[{"item_key": "a"}])

    result = runner.run(make_context(persistence))

    assert result.status is RunStatus.SUCCESS
    assert events.index("process_item:a") < events.index("upsert_item_result:a:success")
    assert persistence.results == result.results


def test_portal_error_becomes_failed_item_result_and_batch_continues() -> None:
    """Verify that portal error becomes failed item result and batch continues.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    persistence = FakePersistence(events)
    runner = FakeRunner(
        items=[{"item_key": "a"}, {"item_key": "b"}],
        behavior={"a": "portal_error"},
    )

    result = runner.run(make_context(persistence))

    failed = result.results[0]
    assert failed.item_key == "a"
    assert failed.status is ItemStatus.FAILED
    assert failed.reason_code is ReasonCode.PORTAL_TIMEOUT
    assert failed.error_detail == "temporary failure"
    assert failed.attempts == 2
    assert result.results[1].item_key == "b"
    assert result.status is RunStatus.PARTIAL_SUCCESS
    assert "process_item:b" in events


def test_unexpected_item_error_becomes_unexpected_error_result() -> None:
    """Verify that unexpected item error becomes unexpected error result.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    persistence = FakePersistence([])
    runner = FakeRunner(items=[{"item_key": "a"}], behavior={"a": "unexpected"})

    result = runner.run(make_context(persistence))

    assert result.status is RunStatus.FAILED
    assert result.results[0].reason_code is ReasonCode.UNEXPECTED_ERROR
    assert result.results[0].error_detail == "unexpected failure"
    assert result.results[0].attempts == 1


def test_all_item_level_failures_still_finalize_and_finish_run() -> None:
    """Verify that all item level failures still finalize and finish run.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    persistence = FakePersistence(events)
    runner = FakeRunner(
        items=[{"item_key": "a"}, {"item_key": "b"}],
        behavior={"a": "portal_error", "b": "unexpected"},
    )

    result = runner.run(make_context(persistence))

    assert result.status is RunStatus.FAILED
    assert runner.finalized_result is result
    assert events[-2:] == ["finalize:failed", "finish_run:failed"]
    assert persistence.finished == (
        "run-1",
        RunStatus.FAILED,
        {"total": 2, "success": 0, "failed": 2, "skipped": 0},
    )


def test_all_successes_status_is_success_and_summary_counts_successes() -> None:
    """Verify that all successes status is success and summary counts successes.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    persistence = FakePersistence(events)
    runner = FakeRunner(items=[{"item_key": "a"}, {"item_key": "b"}])

    result = runner.run(make_context(persistence))

    assert result.status is RunStatus.SUCCESS
    assert persistence.finished == (
        "run-1",
        RunStatus.SUCCESS,
        {"total": 2, "success": 2, "failed": 0, "skipped": 0},
    )


def test_persistence_failure_in_mark_item_in_progress_is_logged_and_raised() -> None:
    """Verify that persistence failure in mark item in progress is logged and raised.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    logger = FakeLogger()
    persistence = FakePersistence(events, fail_on_mark=True)
    runner = FakeRunner(items=[{"item_key": "a"}])

    with pytest.raises(RuntimeError, match="mark failed"):
        runner.run(make_context(persistence, logger=logger))

    assert logger.errors == [("persistence_failure", {"error": "mark failed"})]
    assert "finalize" not in runner.events
    assert not any(event.startswith("finish_run") for event in events)


def test_persistence_failure_in_upsert_item_result_is_logged_and_raised() -> None:
    """Verify that persistence failure in upsert item result is logged and raised.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    events: list[str] = []
    logger = FakeLogger()
    persistence = FakePersistence(events, fail_on_upsert=True)
    runner = FakeRunner(items=[{"item_key": "a"}])

    with pytest.raises(RuntimeError, match="upsert failed"):
        runner.run(make_context(persistence, logger=logger))

    assert logger.errors == [("persistence_failure", {"error": "upsert failed"})]
    assert "finalize" not in runner.events
    assert not any(event.startswith("finish_run") for event in events)


def test_item_key_default_supports_dict_attribute_and_string_fallback() -> None:
    """Verify that item key default supports dict attribute and string fallback.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    runner = FakeRunner(items=[])

    assert runner.item_key({"item_key": 123}) == "123"
    assert runner.item_key(ObjectItem(item_key="abc")) == "abc"
    assert runner.item_key("plain-item") == "plain-item"


def test_runner_source_does_not_reference_browser_automation_symbols() -> None:
    """Verify that runner source does not reference browser automation symbols.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/core/runner.py").read_text(encoding="utf-8").lower()

    assert "playwright" not in source
    assert "browser" not in source
    assert "page" not in source


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


def test_failed_item_captures_diagnostics_without_masking_portal_error() -> None:
    """Verify that failed item captures diagnostics without masking portal error.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    persistence = FakePersistence([])
    logger = FakeLogger()
    diagnostics = DiagnosticsStub()
    runner = FakeRunner(items=[{"item_key": "a"}], behavior={"a": "portal_error"})

    result = runner.run(make_context(persistence, logger=logger, diagnostics=diagnostics))

    failed = result.results[0]
    assert failed.status is ItemStatus.FAILED
    assert failed.reason_code is ReasonCode.PORTAL_TIMEOUT
    assert failed.details["diagnostics"] == {
        "screenshot_path": "/artifacts/fakeportal/a_failure.png",
        "trace_path": "/artifacts/fakeportal/a_trace.zip",
    }
    assert diagnostics.calls == [
        {
            "run_id": "run-1",
            "portal_name": "fakeportal",
            "item_key": "a",
            "artifacts": {},
        }
    ]
    assert (
        "failure_diagnostics_captured",
        {
            "item_key": "a",
            "screenshot_path": "/artifacts/fakeportal/a_failure.png",
            "trace_path": "/artifacts/fakeportal/a_trace.zip",
        },
    ) in logger.infos


def test_diagnostic_failure_does_not_mask_original_item_error() -> None:
    """Verify that diagnostic failure does not mask original item error.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    persistence = FakePersistence([])
    logger = FakeLogger()
    diagnostics = DiagnosticsStub(error=RuntimeError("diagnostics failed"))
    runner = FakeRunner(items=[{"item_key": "a"}], behavior={"a": "portal_error"})

    result = runner.run(make_context(persistence, logger=logger, diagnostics=diagnostics))

    failed = result.results[0]
    assert failed.status is ItemStatus.FAILED
    assert failed.reason_code is ReasonCode.PORTAL_TIMEOUT
    assert failed.details == {}
    assert (
        "failure_diagnostics_failed",
        {"item_key": "a", "error": "diagnostics failed"},
    ) in logger.errors


def test_dry_run_does_not_attempt_failure_diagnostics() -> None:
    """Verify that dry run does not attempt failure diagnostics.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    persistence = FakePersistence([])
    diagnostics = DiagnosticsStub()
    runner = FakeRunner(items=[{"item_key": "a"}], behavior={"a": "portal_error"})

    runner.run(make_context(persistence, dry_run=True, diagnostics=diagnostics))

    assert diagnostics.calls == []
