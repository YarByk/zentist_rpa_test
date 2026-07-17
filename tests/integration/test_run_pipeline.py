import json
import sqlite3
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.email_connector import EmailConnector
from portal_automation.core.models import (
    ItemResult,
    ItemStatus,
    ReasonCode,
    RunContext,
    RunResult,
    RunStatus,
)
from portal_automation.core.observability import RunMetricsCollector, StructuredEventLogger
from portal_automation.core.persistence import PersistenceConnector
from portal_automation.core.reporting import ReportGenerator
from portal_automation.core.retries import PortalError
from portal_automation.core.runner import BasePortalRunnerZX

FAKE_PORTAL = "integration_test"
FAKE_OPERATION = "test_op"
BUSINESS_DATE = date(2026, 1, 15)


class FakeRunner(BasePortalRunnerZX):
    """Local integration runner. Not in the registry. No Playwright. No real portals."""

    portal_name = FAKE_PORTAL
    operation_name = FAKE_OPERATION

    def __init__(self, items: list[dict[str, Any]], *, send_email: bool = False) -> None:
        """Initialize this test helper instance.

        Args:
            items: Value supplied by the test or fixture for `items`.
            send_email: Value supplied by the test or fixture for `send_email`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self._items = items
        self._send_email = send_email
        self.processed_keys: list[str] = []

    def preflight_check(self, context: RunContext) -> None:
        """Preflight check.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return

    def load_items(self, context: RunContext) -> list[dict[str, Any]]:
        """Load items.

        Args:
            context: Value supplied by the test or fixture for `context`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return list(self._items)

    def process_item(self, context: RunContext, item: dict[str, Any]) -> ItemResult:
        """Process item.

        Args:
            context: Value supplied by the test or fixture for `context`.
            item: Value supplied by the test or fixture for `item`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        item_key = str(item["item_key"])
        self.processed_keys.append(item_key)
        if item.get("fail"):
            raise PortalError(
                ReasonCode.PORTAL_TIMEOUT,
                f"{item_key} timed out",
            )
        return ItemResult(
            item_key=item_key,
            operation=self.operation_name,
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            details={"note": "integration test"},
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
        if hasattr(context.reporter, "write_report"):
            context.reporter.write_report(result)
        if self._send_email and hasattr(context.email, "send_report"):
            if hasattr(context.reporter, "render"):
                body = context.reporter.render(result)
            else:
                body = ""
            context.email.send_report(
                run_id=context.run_id,
                to=None,
                subject=f"Integration test report: {context.run_id}",
                body=body,
            )


def make_context(
    tmp_path: Path,
    *,
    run_id: str | None = None,
    dry_run: bool = False,
    persistence: PersistenceConnector | None = None,
) -> RunContext:
    # Build a full integration context backed by the real artifact, report, email, and DB helpers.
    """Make context.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        run_id: Value supplied by the test or fixture for `run_id`.
        dry_run: Value supplied by the test or fixture for `dry_run`.
        persistence: Value supplied by the test or fixture for `persistence`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    metrics = RunMetricsCollector(
        artifacts,
        run_id=run_id,
        portal=FAKE_PORTAL,
        business_date=BUSINESS_DATE,
    )
    logger = StructuredEventLogger(
        artifacts,
        run_id=run_id,
        portal=FAKE_PORTAL,
        business_date=BUSINESS_DATE,
        metrics=metrics,
    )
    return RunContext(
        run_id=run_id,
        business_date=BUSINESS_DATE,
        dry_run=dry_run,
        stale_item_timeout_seconds=300,
        config=object(),
        persistence=(persistence or PersistenceConnector(str(tmp_path / "db.sqlite"))),
        reporter=ReportGenerator(artifacts, logger=logger),
        logger=logger,
        metrics=metrics,
        artifacts=artifacts,
        email=EmailConnector("dry_run", artifacts, logger=logger),
    )


def fetch_rows(db_path: Path, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    # Small sqlite helper used to assert persisted state after the pipeline run completes.
    """Fetch rows.

    Args:
        db_path: Value supplied by the test or fixture for `db_path`.
        query: Value supplied by the test or fixture for `query`.
        params: Value supplied by the test or fixture for `params`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query, params).fetchall()
    finally:
        connection.close()


def test_runner_pipeline_persists_run_results_report_and_dry_run_email(tmp_path: Path) -> None:
    # -------------------------------------------------------------------------
    # End-to-end integration check for the shared pipeline:
    # 1. Run the fake runner against real connectors.
    # 2. Verify DB writes for the run and item results.
    # 3. Verify generated report, email artifact, events, and metrics.
    # -------------------------------------------------------------------------
    """Verify that runner pipeline persists run results report and dry run email.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    run_id = "pipeline-run"
    context = make_context(tmp_path, run_id=run_id, dry_run=False)
    runner = FakeRunner(
        [{"item_key": "item-a"}, {"item_key": "item-b"}],
        send_email=True,
    )

    result = runner.run(context)

    assert result.status is RunStatus.SUCCESS
    assert runner.processed_keys == ["item-a", "item-b"]

    db_path = tmp_path / "db.sqlite"
    run_rows = fetch_rows(db_path, "SELECT * FROM runs WHERE run_id = ?", (run_id,))
    assert len(run_rows) == 1
    run_row = run_rows[0]
    assert run_row["portal_name"] == FAKE_PORTAL
    assert run_row["business_date"] == BUSINESS_DATE.isoformat()
    assert run_row["status"] == RunStatus.SUCCESS.value
    assert run_row["finished_at"] is not None
    assert json.loads(run_row["summary_json"]) == {
        "failed": 0,
        "skipped": 0,
        "success": 2,
        "total": 2,
    }

    item_rows = fetch_rows(
        db_path,
        """
        SELECT portal_name, business_date, item_key, operation, status
        FROM item_results
        WHERE portal_name = ?
        ORDER BY item_key
        """,
        (FAKE_PORTAL,),
    )
    assert [dict(row) for row in item_rows] == [
        {
            "portal_name": FAKE_PORTAL,
            "business_date": BUSINESS_DATE.isoformat(),
            "item_key": "item-a",
            "operation": FAKE_OPERATION,
            "status": ItemStatus.SUCCESS.value,
        },
        {
            "portal_name": FAKE_PORTAL,
            "business_date": BUSINESS_DATE.isoformat(),
            "item_key": "item-b",
            "operation": FAKE_OPERATION,
            "status": ItemStatus.SUCCESS.value,
        },
    ]
    count_rows = fetch_rows(
        db_path,
        """
        SELECT COUNT(*) AS count
        FROM item_results
        WHERE business_date = ?
          AND portal_name = ?
          AND operation = ?
        """,
        (BUSINESS_DATE.isoformat(), FAKE_PORTAL, FAKE_OPERATION),
    )
    assert count_rows[0]["count"] == 2

    report_path = tmp_path / "artifacts" / "runs" / run_id / "report.txt"
    assert report_path.is_file()
    report = report_path.read_text(encoding="utf-8")
    assert f"Run ID: {run_id}" in report
    assert f"Portal: {FAKE_PORTAL}" in report
    assert "item_key=item-a" in report
    assert "item_key=item-b" in report

    email_path = tmp_path / "artifacts" / "runs" / run_id / "email_report.txt"
    assert email_path.is_file()
    email_report = email_path.read_text(encoding="utf-8")
    assert email_report.startswith(f"To: \nSubject: Integration test report: {run_id}\n\n")
    assert "item_key=item-a" in email_report
    assert "item_key=item-b" in email_report

    events_path = tmp_path / "artifacts" / "runs" / run_id / "events.jsonl"
    metrics_path = tmp_path / "artifacts" / "runs" / run_id / "metrics.json"
    assert events_path.is_file()
    assert metrics_path.is_file()
    event_rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert {row["event"] for row in event_rows} >= {
        "run_started",
        "item_started",
        "item_finished",
        "report_generated",
        "email_send_attempt",
        "email_sent",
        "run_finished",
    }
    for row in event_rows:
        assert row["run_id"] == run_id
        assert row["portal"] == FAKE_PORTAL
        assert row["business_date"] == BUSINESS_DATE.isoformat()
        assert row["timestamp"]
        assert row["event"]
    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics_payload["run_id"] == run_id
    assert metrics_payload["portal"] == FAKE_PORTAL
    assert metrics_payload["business_date"] == BUSINESS_DATE.isoformat()
    assert metrics_payload["items_total"] == 2
    assert metrics_payload["items_success"] == 2
    assert metrics_payload["items_failed"] == 0
    assert metrics_payload["items_skipped"] == 0
    assert metrics_payload["retry_count"] == 0
    assert metrics_payload["duration_seconds"] >= 0


def test_runner_pipeline_records_partial_success_for_mixed_item_results(
    tmp_path: Path,
) -> None:
    """Verify that runner pipeline records partial success for mixed item results.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    run_id = "partial-run"
    context = make_context(tmp_path, run_id=run_id, dry_run=False)
    runner = FakeRunner(
        [
            {"item_key": "item-ok"},
            {"item_key": "item-bad", "fail": True},
            {"item_key": "item-later"},
        ],
    )

    result = runner.run(context)

    assert result.status is RunStatus.PARTIAL_SUCCESS
    assert runner.processed_keys == ["item-ok", "item-bad", "item-later"]

    rows = fetch_rows(
        tmp_path / "db.sqlite",
        """
        SELECT item_key, status, reason_code
        FROM item_results
        WHERE portal_name = ?
        ORDER BY item_key
        """,
        (FAKE_PORTAL,),
    )
    assert [dict(row) for row in rows] == [
        {
            "item_key": "item-bad",
            "status": ItemStatus.FAILED.value,
            "reason_code": ReasonCode.PORTAL_TIMEOUT.value,
        },
        {
            "item_key": "item-later",
            "status": ItemStatus.SUCCESS.value,
            "reason_code": None,
        },
        {
            "item_key": "item-ok",
            "status": ItemStatus.SUCCESS.value,
            "reason_code": None,
        },
    ]

    report_path = tmp_path / "artifacts" / "runs" / run_id / "report.txt"
    assert report_path.is_file()
    report = report_path.read_text(encoding="utf-8")
    assert "Run status: partial_success" in report
    assert "item_key=item-ok" in report
    assert "item_key=item-bad" in report
    assert "item_key=item-later" in report

    metrics_payload = json.loads(
        (tmp_path / "artifacts" / "runs" / run_id / "metrics.json").read_text(encoding="utf-8")
    )
    assert metrics_payload["items_total"] == 3
    assert metrics_payload["items_success"] == 2
    assert metrics_payload["items_failed"] == 1
