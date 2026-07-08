import sqlite3
import subprocess
import sys
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
from portal_automation.core.persistence import PersistenceConnector
from portal_automation.core.reporting import ReportGenerator
from portal_automation.core.retries import PortalError
from portal_automation.core.runner import BasePortalRunnerZX

FAKE_PORTAL = "integration_test"
FAKE_OPERATION = "test_op"
BUSINESS_DATE = date(2026, 1, 15)
OTHER_BUSINESS_DATE = date(2026, 1, 16)
OLD_TIMESTAMP = "2024-01-01T00:00:00+00:00"


class FakeRunner(BasePortalRunnerZX):
    """Local integration runner. Not in the registry. No Playwright. No real portals."""

    portal_name = FAKE_PORTAL
    operation_name = FAKE_OPERATION

    def __init__(self, items: list[dict[str, Any]], *, send_email: bool = False) -> None:
        self._items = items
        self._send_email = send_email
        self.processed_keys: list[str] = []

    def preflight_check(self, context: RunContext) -> None:
        return

    def load_items(self, context: RunContext) -> list[dict[str, Any]]:
        return list(self._items)

    def process_item(self, context: RunContext, item: dict[str, Any]) -> ItemResult:
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
    run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    return RunContext(
        run_id=run_id,
        business_date=BUSINESS_DATE,
        dry_run=dry_run,
        stale_item_timeout_seconds=300,
        config=object(),
        persistence=(
            persistence or PersistenceConnector(str(tmp_path / "db.sqlite"))
        ),
        reporter=ReportGenerator(artifacts),
        logger=object(),
        metrics=object(),
        artifacts=artifacts,
        email=EmailConnector("dry_run", artifacts),
    )


def fetch_rows(db_path: Path, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query, params).fetchall()
    finally:
        connection.close()


def set_item_updated_at(db_path: Path, item_key: str, updated_at: str) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE item_results SET updated_at = ? WHERE item_key = ?",
            (updated_at, item_key),
        )
        connection.commit()
    finally:
        connection.close()


def set_run_updated_at(db_path: Path, run_id: str, updated_at: str) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE runs SET updated_at = ? WHERE run_id = ?",
            (updated_at, run_id),
        )
        connection.commit()
    finally:
        connection.close()


def count_item_rows(db_path: Path) -> int:
    rows = fetch_rows(
        db_path,
        "SELECT COUNT(*) AS count FROM item_results WHERE portal_name = ?",
        (FAKE_PORTAL,),
    )
    return int(rows[0]["count"])


def run_recover_cli(tmp_path: Path, *args: str):
    env = {
        **__import__("os").environ,
        "DB_PATH": str(tmp_path / "db.sqlite"),
        "ARTIFACTS_DIR": str(tmp_path / "artifacts"),
        "EMAIL_BACKEND": "dry_run",
    }
    return subprocess.run(
        [sys.executable, "-m", "portal_automation", "recover", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_same_day_rerun_skips_committed_items_and_keeps_report_complete(
    tmp_path: Path,
) -> None:
    persistence = PersistenceConnector(str(tmp_path / "db.sqlite"))
    runner1 = FakeRunner([{"item_key": "item-a"}, {"item_key": "item-b"}])
    context1 = make_context(
        tmp_path,
        run_id="run-1",
        persistence=persistence,
        dry_run=False,
    )
    runner1.run(context1)

    assert persistence.get_committed_items(FAKE_PORTAL, BUSINESS_DATE) == {
        "item-a",
        "item-b",
    }

    runner2 = FakeRunner([{"item_key": "item-a"}, {"item_key": "item-b"}])
    context2 = make_context(
        tmp_path,
        run_id="run-2",
        persistence=persistence,
        dry_run=False,
    )
    result2 = runner2.run(context2)

    assert result2.status is RunStatus.SUCCESS
    assert runner2.processed_keys == []
    assert {item.item_key for item in result2.results} == {"item-a", "item-b"}
    assert count_item_rows(tmp_path / "db.sqlite") == 2
    assert persistence.get_committed_items(FAKE_PORTAL, BUSINESS_DATE) == {
        "item-a",
        "item-b",
    }

    report = (tmp_path / "artifacts" / "runs" / "run-2" / "report.txt").read_text(
        encoding="utf-8"
    )
    assert "item_key=item-a" in report
    assert "item_key=item-b" in report


def test_recovery_state_keeps_committed_item_and_reprocesses_uncommitted_item(
    tmp_path: Path,
) -> None:
    persistence = PersistenceConnector(str(tmp_path / "db.sqlite"))

    persistence.create_run("run-old", FAKE_PORTAL, BUSINESS_DATE)
    persistence.mark_item_in_progress(
        "run-old",
        FAKE_PORTAL,
        BUSINESS_DATE,
        "item-a",
        FAKE_OPERATION,
    )
    persistence.upsert_item_result(
        ItemResult(
            item_key="item-a",
            operation=FAKE_OPERATION,
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            details={},
        ),
        "run-old",
        FAKE_PORTAL,
        BUSINESS_DATE,
    )
    persistence.mark_item_in_progress(
        "run-old",
        FAKE_PORTAL,
        BUSINESS_DATE,
        "item-b",
        FAKE_OPERATION,
    )

    assert persistence.get_committed_items(FAKE_PORTAL, BUSINESS_DATE) == {"item-a"}

    runner = FakeRunner([{"item_key": "item-a"}, {"item_key": "item-b"}])
    context = make_context(
        tmp_path,
        run_id="run-new",
        persistence=persistence,
        dry_run=False,
    )
    result = runner.run(context)

    assert result.status is RunStatus.SUCCESS
    assert runner.processed_keys == ["item-b"]
    assert persistence.get_committed_items(FAKE_PORTAL, BUSINESS_DATE) == {
        "item-a",
        "item-b",
    }
    assert count_item_rows(tmp_path / "db.sqlite") == 2
    assert {
        result.item_key: result.status for result in result.results
    } == {
        "item-a": ItemStatus.SUCCESS,
        "item-b": ItemStatus.SUCCESS,
    }


def test_stale_in_progress_item_detection_uses_portal_and_business_date(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "db.sqlite"
    persistence = PersistenceConnector(str(db_path))
    persistence.mark_item_in_progress(
        "run-stale",
        FAKE_PORTAL,
        BUSINESS_DATE,
        "item-stale",
        FAKE_OPERATION,
    )
    persistence.mark_item_in_progress(
        "run-fresh",
        FAKE_PORTAL,
        BUSINESS_DATE,
        "item-fresh",
        FAKE_OPERATION,
    )
    persistence.mark_item_in_progress(
        "run-other-portal",
        "other_portal",
        BUSINESS_DATE,
        "item-other-portal",
        FAKE_OPERATION,
    )
    persistence.mark_item_in_progress(
        "run-other-date",
        FAKE_PORTAL,
        OTHER_BUSINESS_DATE,
        "item-other-date",
        FAKE_OPERATION,
    )
    set_item_updated_at(db_path, "item-stale", OLD_TIMESTAMP)
    set_item_updated_at(db_path, "item-other-portal", OLD_TIMESTAMP)
    set_item_updated_at(db_path, "item-other-date", OLD_TIMESTAMP)

    stale_items = persistence.find_stale_items(
        FAKE_PORTAL,
        BUSINESS_DATE,
        timeout_seconds=300,
    )

    assert [item["item_key"] for item in stale_items] == ["item-stale"]
    assert persistence.find_stale_items("missing_portal", BUSINESS_DATE, 300) == []
    assert persistence.find_stale_items(FAKE_PORTAL, date(2026, 1, 17), 300) == []


def test_stale_run_detection_uses_finished_at_and_timeout(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    persistence = PersistenceConnector(str(db_path))
    persistence.create_run("run-hanging", FAKE_PORTAL, BUSINESS_DATE)
    persistence.create_run("run-fresh", FAKE_PORTAL, BUSINESS_DATE)
    persistence.create_run("run-finished", FAKE_PORTAL, BUSINESS_DATE)
    persistence.finish_run("run-finished", RunStatus.SUCCESS, {"total": 0})
    set_run_updated_at(db_path, "run-hanging", OLD_TIMESTAMP)
    set_run_updated_at(db_path, "run-finished", OLD_TIMESTAMP)

    stale_runs = persistence.find_stale_runs(timeout_seconds=300)

    assert [run["run_id"] for run in stale_runs] == ["run-hanging"]
    assert persistence.mark_run_stale("run-hanging", timeout_seconds=1) is True
    assert persistence.mark_run_stale("run-hanging", timeout_seconds=300) is False


def test_recover_dry_run_reports_stale_rows_without_modifying_database(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    persistence = PersistenceConnector(str(db_path))
    persistence.create_run("run-stale", FAKE_PORTAL, BUSINESS_DATE)
    persistence.mark_item_in_progress(
        "run-stale",
        FAKE_PORTAL,
        BUSINESS_DATE,
        "item-stale",
        FAKE_OPERATION,
    )
    set_run_updated_at(db_path, "run-stale", OLD_TIMESTAMP)
    set_item_updated_at(db_path, "item-stale", OLD_TIMESTAMP)

    result = run_recover_cli(
        tmp_path,
        "--business-date",
        BUSINESS_DATE.isoformat(),
        "--dry-run",
    )

    assert result.returncode == 0
    assert "stale_runs_found=1" in result.stdout
    assert "stale_items_found=1" in result.stdout
    assert "dry_run=true database_unchanged=true" in result.stdout
    run_row = fetch_rows(db_path, "SELECT status FROM runs WHERE run_id = ?", ("run-stale",))[0]
    item_row = fetch_rows(
        db_path,
        "SELECT status, reason_code FROM item_results WHERE item_key = ?",
        ("item-stale",),
    )[0]
    assert run_row["status"] == RunStatus.RUNNING.value
    assert item_row["status"] == ItemStatus.IN_PROGRESS.value
    assert item_row["reason_code"] is None
    recover_dirs = list((tmp_path / "artifacts" / "runs").iterdir())
    assert len(recover_dirs) == 1
    assert (recover_dirs[0] / "events.jsonl").is_file()
    assert (recover_dirs[0] / "metrics.json").is_file()


def test_recover_marks_only_safe_stale_rows_and_keeps_success_items_untouched(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "db.sqlite"
    persistence = PersistenceConnector(str(db_path))
    persistence.create_run("run-stale", FAKE_PORTAL, BUSINESS_DATE)
    persistence.create_run("run-fresh", FAKE_PORTAL, BUSINESS_DATE)
    persistence.mark_item_in_progress(
        "run-stale",
        FAKE_PORTAL,
        BUSINESS_DATE,
        "item-stale",
        FAKE_OPERATION,
    )
    persistence.mark_item_in_progress(
        "run-fresh",
        FAKE_PORTAL,
        BUSINESS_DATE,
        "item-fresh",
        FAKE_OPERATION,
    )
    persistence.upsert_item_result(
        ItemResult(
            item_key="item-success",
            operation=FAKE_OPERATION,
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            details={},
        ),
        "run-success",
        FAKE_PORTAL,
        BUSINESS_DATE,
    )
    set_run_updated_at(db_path, "run-stale", OLD_TIMESTAMP)
    set_item_updated_at(db_path, "item-stale", OLD_TIMESTAMP)

    result = run_recover_cli(tmp_path, "--business-date", BUSINESS_DATE.isoformat())

    assert result.returncode == 0
    assert "stale_runs_marked=1" in result.stdout
    assert "stale_items_marked_failed=1" in result.stdout
    run_rows = fetch_rows(
        db_path,
        "SELECT run_id, status FROM runs ORDER BY run_id",
    )
    item_rows = fetch_rows(
        db_path,
        "SELECT item_key, status, reason_code FROM item_results ORDER BY item_key",
    )
    run_status_by_id = {row["run_id"]: row["status"] for row in run_rows}
    assert run_status_by_id["run-stale"] == RunStatus.STALE.value
    assert run_status_by_id["run-fresh"] == RunStatus.RUNNING.value
    item_by_key = {row["item_key"]: row for row in item_rows}
    assert item_by_key["item-stale"]["status"] == ItemStatus.FAILED.value
    assert item_by_key["item-stale"]["reason_code"] == ReasonCode.SESSION_DROPPED.value
    assert item_by_key["item-fresh"]["status"] == ItemStatus.IN_PROGRESS.value
    assert item_by_key["item-fresh"]["reason_code"] is None
    assert item_by_key["item-success"]["status"] == ItemStatus.SUCCESS.value
    assert item_by_key["item-success"]["reason_code"] is None
