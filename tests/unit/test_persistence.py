import json
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from portal_automation.core.models import ItemResult, ItemStatus, ReasonCode, RunStatus
from portal_automation.core.persistence import PersistenceConnector

ROOT = Path(__file__).resolve().parents[2]


def connector(tmp_path: Path) -> PersistenceConnector:
    # Create a fresh database in a nested path to verify parent directory creation too.
    """Connector.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return PersistenceConnector(str(tmp_path / "nested" / "portal.sqlite"))


def fetch_one(db: PersistenceConnector, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row:
    # Convenience helper for assertions that expect exactly one row to exist.
    """Fetch one.
    
    Args:
        db: Value supplied by the test or fixture for `db`.
        sql: Value supplied by the test or fixture for `sql`.
        params: Value supplied by the test or fixture for `params`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    row = db._connection.execute(sql, params).fetchone()
    assert row is not None
    return row


def successful_item(
    item_key: str = "employee-100",
    details: dict[str, object] | None = None,
) -> ItemResult:
    # Reusable successful item fixture with non-sorted details for JSON ordering checks.
    """Successful item.
    
    Args:
        item_key: Value supplied by the test or fixture for `item_key`.
        details: Value supplied by the test or fixture for `details`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return ItemResult(
        item_key=item_key,
        operation="sync_employee_state",
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path="artifacts/runs/run-1/employee-100.txt",
        attempts=2,
        details=details or {"z": 2, "a": 1},
    )


def utc_stamp(seconds_delta: int) -> str:
    # Build relative UTC timestamps for stale-state tests.
    """Utc stamp.
    
    Args:
        seconds_delta: Value supplied by the test or fixture for `seconds_delta`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return (datetime.now(UTC) + timedelta(seconds=seconds_delta)).isoformat(timespec="microseconds")


def set_item_updated_at(db: PersistenceConnector, item_key: str, updated_at: str) -> None:
    """Set item updated at.
    
    Args:
        db: Value supplied by the test or fixture for `db`.
        item_key: Value supplied by the test or fixture for `item_key`.
        updated_at: Value supplied by the test or fixture for `updated_at`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db._connection.execute(
        "UPDATE item_results SET updated_at = ? WHERE item_key = ?",
        (updated_at, item_key),
    )
    db._connection.commit()


def set_run_updated_at(db: PersistenceConnector, run_id: str, updated_at: str) -> None:
    """Set run updated at.
    
    Args:
        db: Value supplied by the test or fixture for `db`.
        run_id: Value supplied by the test or fixture for `run_id`.
        updated_at: Value supplied by the test or fixture for `updated_at`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db._connection.execute(
        "UPDATE runs SET updated_at = ? WHERE run_id = ?",
        (updated_at, run_id),
    )
    db._connection.commit()


def test_schema_initializes_required_tables_and_columns(tmp_path: Path) -> None:
    # Connecting to a new path should initialize the database schema automatically.
    """Verify that schema initializes required tables and columns.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)

    runs_columns = {
        row["name"] for row in db._connection.execute("PRAGMA table_info(runs)").fetchall()
    }
    item_columns = {
        row["name"] for row in db._connection.execute("PRAGMA table_info(item_results)").fetchall()
    }

    assert (tmp_path / "nested" / "portal.sqlite").exists()
    assert "updated_at" in runs_columns
    assert "error_detail" in item_columns


def test_item_results_has_required_unique_constraint(tmp_path: Path) -> None:
    # The business idempotency key is enforced by a unique index on item_results.
    """Verify that item results has required unique constraint.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    indexes = db._connection.execute("PRAGMA index_list(item_results)").fetchall()

    unique_columns = []
    for index in indexes:
        if index["unique"]:
            columns = [
                row["name"]
                for row in db._connection.execute(
                    f"PRAGMA index_info({index['name']})",
                ).fetchall()
            ]
            unique_columns.append(columns)

    assert ["business_date", "portal_name", "item_key", "operation"] in unique_columns


def test_create_run_creates_running_run_row(tmp_path: Path) -> None:
    """Verify that create run creates running run row.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)

    db.create_run("run-1", "orangehrm", date(2026, 6, 29))

    row = fetch_one(db, "SELECT * FROM runs WHERE run_id = ?", ("run-1",))
    assert row["portal_name"] == "orangehrm"
    assert row["business_date"] == "2026-06-29"
    assert row["status"] == RunStatus.RUNNING.value
    assert row["started_at"]
    assert row["updated_at"]
    assert row["finished_at"] is None
    assert row["summary_json"] is None


def test_finish_run_sets_final_status_and_sorted_summary_json(tmp_path: Path) -> None:
    """Verify that finish run sets final status and sorted summary json.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    db.create_run("run-1", "orangehrm", date(2026, 6, 29))
    before = fetch_one(db, "SELECT updated_at FROM runs WHERE run_id = ?", ("run-1",))
    time.sleep(0.001)

    db.finish_run("run-1", RunStatus.SUCCESS, {"z": 2, "a": 1})

    row = fetch_one(db, "SELECT * FROM runs WHERE run_id = ?", ("run-1",))
    assert row["status"] == RunStatus.SUCCESS.value
    assert row["finished_at"]
    assert row["updated_at"] != before["updated_at"]
    assert row["summary_json"] == '{"a": 1, "z": 2}'


def test_mark_item_in_progress_creates_in_progress_row(tmp_path: Path) -> None:
    """Verify that mark item in progress creates in progress row.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)

    db.mark_item_in_progress(
        "run-1",
        "orangehrm",
        date(2026, 6, 29),
        "employee-100",
        "sync_employee_state",
    )

    row = fetch_one(db, "SELECT * FROM item_results WHERE item_key = ?", ("employee-100",))
    assert row["run_id"] == "run-1"
    assert row["portal_name"] == "orangehrm"
    assert row["business_date"] == "2026-06-29"
    assert row["operation"] == "sync_employee_state"
    assert row["status"] == ItemStatus.IN_PROGRESS.value
    assert row["reason_code"] is None
    assert row["error_detail"] is None
    assert row["attempts"] == 1
    assert row["artifact_path"] is None
    assert row["details_json"] == "{}"
    assert row["created_at"]
    assert row["updated_at"]


def test_upsert_item_result_inserts_and_lists_item_result(tmp_path: Path) -> None:
    """Verify that upsert item result inserts and lists item result.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    result = successful_item()

    db.upsert_item_result(result, "run-1", "orangehrm", date(2026, 6, 29))

    results = db.list_results_for_run("run-1")
    assert results == [result]


def test_upserting_same_item_updates_one_row_and_preserves_created_at(tmp_path: Path) -> None:
    # Upsert should replace the business result while preserving the original creation timestamp.
    """Verify that upserting same item updates one row and preserves created at.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    original = successful_item(details={"z": 2, "a": 1})
    updated = ItemResult(
        item_key="employee-100",
        operation="sync_employee_state",
        status=ItemStatus.FAILED,
        reason_code=ReasonCode.ITEM_NOT_FOUND,
        error_detail="employee not found",
        artifact_path="artifacts/runs/run-2/failure.png",
        attempts=3,
        details={"new": True},
    )

    db.upsert_item_result(original, "run-1", "orangehrm", date(2026, 6, 29))
    first_row = fetch_one(db, "SELECT * FROM item_results WHERE item_key = ?", ("employee-100",))
    time.sleep(0.001)
    db.upsert_item_result(updated, "run-2", "orangehrm", date(2026, 6, 29))
    second_row = fetch_one(db, "SELECT * FROM item_results WHERE item_key = ?", ("employee-100",))
    count = fetch_one(db, "SELECT COUNT(*) AS count FROM item_results")

    assert count["count"] == 1
    assert second_row["created_at"] == first_row["created_at"]
    assert second_row["updated_at"] != first_row["updated_at"]
    assert second_row["run_id"] == "run-2"
    assert second_row["status"] == ItemStatus.FAILED.value
    assert second_row["reason_code"] == ReasonCode.ITEM_NOT_FOUND.value
    assert second_row["error_detail"] == "employee not found"
    assert second_row["attempts"] == 3
    assert second_row["artifact_path"] == "artifacts/runs/run-2/failure.png"
    assert json.loads(second_row["details_json"]) == {"new": True}
    assert db.list_results_for_run("run-2") == [updated]


def test_details_json_is_stored_with_sorted_keys(tmp_path: Path) -> None:
    """Verify that details json is stored with sorted keys.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)

    db.upsert_item_result(
        successful_item(details={"z": 2, "a": 1}),
        "run-1",
        "orangehrm",
        date(2026, 6, 29),
    )

    row = fetch_one(
        db,
        "SELECT details_json FROM item_results WHERE item_key = ?",
        ("employee-100",),
    )
    assert row["details_json"] == '{"a": 1, "z": 2}'


def test_mark_item_in_progress_conflict_resets_transient_fields(tmp_path: Path) -> None:
    # Reclaiming an item for a rerun should clear the previous failure/result fields.
    """Verify that mark item in progress conflict resets transient fields.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    db.upsert_item_result(
        ItemResult(
            item_key="employee-100",
            operation="sync_employee_state",
            status=ItemStatus.FAILED,
            reason_code=ReasonCode.VALIDATION_FAILED,
            error_detail="bad state",
            artifact_path="artifacts/failure.png",
            attempts=4,
            details={"failure": True},
        ),
        "run-1",
        "orangehrm",
        date(2026, 6, 29),
    )
    first_row = fetch_one(db, "SELECT * FROM item_results WHERE item_key = ?", ("employee-100",))
    time.sleep(0.001)

    db.mark_item_in_progress(
        "run-2",
        "orangehrm",
        date(2026, 6, 29),
        "employee-100",
        "sync_employee_state",
    )

    second_row = fetch_one(db, "SELECT * FROM item_results WHERE item_key = ?", ("employee-100",))
    assert second_row["created_at"] == first_row["created_at"]
    assert second_row["updated_at"] != first_row["updated_at"]
    assert second_row["run_id"] == "run-2"
    assert second_row["status"] == ItemStatus.IN_PROGRESS.value
    assert second_row["reason_code"] is None
    assert second_row["error_detail"] is None
    assert second_row["artifact_path"] is None
    assert second_row["attempts"] == 1
    assert second_row["details_json"] == "{}"


def test_reason_code_item_not_found_round_trips_through_sqlite(tmp_path: Path) -> None:
    """Verify that reason code item not found round trips through sqlite.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    result = ItemResult(
        item_key="account-1",
        operation="checkout",
        status=ItemStatus.FAILED,
        reason_code=ReasonCode.ITEM_NOT_FOUND,
        error_detail="missing item",
        artifact_path=None,
        attempts=1,
        details={},
    )

    db.upsert_item_result(result, "run-1", "saucedemo", date(2026, 6, 29))

    assert db.list_results_for_run("run-1") == [result]


def test_get_committed_items_returns_only_same_day_success_keys(tmp_path: Path) -> None:
    """Verify that get committed items returns only same day success keys.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    business_date = date(2026, 6, 29)
    cases = [
        (
            ItemResult(
                item_key="success-1",
                operation="sync_employee_state",
                status=ItemStatus.SUCCESS,
                reason_code=None,
                error_detail=None,
                artifact_path=None,
                attempts=1,
                details={},
            ),
            "orangehrm",
            business_date,
        ),
        (
            ItemResult(
                item_key="failed-1",
                operation="sync_employee_state",
                status=ItemStatus.FAILED,
                reason_code=ReasonCode.VALIDATION_FAILED,
                error_detail="invalid",
                artifact_path=None,
                attempts=1,
                details={},
            ),
            "orangehrm",
            business_date,
        ),
        (
            ItemResult(
                item_key="skipped-1",
                operation="sync_employee_state",
                status=ItemStatus.SKIPPED,
                reason_code=None,
                error_detail=None,
                artifact_path=None,
                attempts=1,
                details={},
            ),
            "orangehrm",
            business_date,
        ),
        (
            ItemResult(
                item_key="other-date-success",
                operation="sync_employee_state",
                status=ItemStatus.SUCCESS,
                reason_code=None,
                error_detail=None,
                artifact_path=None,
                attempts=1,
                details={},
            ),
            "orangehrm",
            date(2026, 6, 28),
        ),
        (
            ItemResult(
                item_key="other-portal-success",
                operation="checkout",
                status=ItemStatus.SUCCESS,
                reason_code=None,
                error_detail=None,
                artifact_path=None,
                attempts=1,
                details={},
            ),
            "saucedemo",
            business_date,
        ),
    ]
    for result, portal_name, result_date in cases:
        db.upsert_item_result(result, f"run-{result.item_key}", portal_name, result_date)
    db.mark_item_in_progress(
        "run-in-progress",
        "orangehrm",
        business_date,
        "in-progress-1",
        "sync_employee_state",
    )

    assert db.get_committed_items("orangehrm", business_date) == {"success-1"}


def test_list_results_by_business_date_filters_and_round_trips_results(
    tmp_path: Path,
) -> None:
    """Verify that list results by business date filters and round trips results.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    business_date = date(2026, 6, 29)
    success = successful_item(item_key="employee-100", details={"employee_id": "100"})
    failed = ItemResult(
        item_key="employee-200",
        operation="sync_employee_state",
        status=ItemStatus.FAILED,
        reason_code=ReasonCode.ITEM_NOT_FOUND,
        error_detail="employee missing",
        artifact_path="artifacts/runs/run-1/employee-200.png",
        attempts=3,
        details={"employee_id": "200", "checked": True},
    )
    other_date = successful_item(item_key="other-date")
    other_portal = ItemResult(
        item_key="account-1",
        operation="checkout",
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
        attempts=1,
        details={"order": "A1"},
    )

    db.upsert_item_result(success, "run-1", "orangehrm", business_date)
    db.upsert_item_result(failed, "run-1", "orangehrm", business_date)
    db.upsert_item_result(other_date, "run-2", "orangehrm", date(2026, 6, 28))
    db.upsert_item_result(other_portal, "run-3", "saucedemo", business_date)

    assert db.list_results_by_business_date("orangehrm", business_date) == [success, failed]


def test_same_day_success_remains_visible_after_another_result_is_written(
    tmp_path: Path,
) -> None:
    """Verify that same day success remains visible after another result is written.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    business_date = date(2026, 6, 29)
    first = successful_item(item_key="employee-100")
    second = successful_item(item_key="employee-200")

    db.upsert_item_result(first, "run-1", "orangehrm", business_date)
    db.upsert_item_result(second, "run-2", "orangehrm", business_date)

    count = fetch_one(db, "SELECT COUNT(*) AS count FROM item_results")
    assert count["count"] == 2
    assert db.list_results_by_business_date("orangehrm", business_date) == [first, second]


def test_same_day_upsert_still_keeps_one_row_per_idempotency_key(tmp_path: Path) -> None:
    """Verify that same day upsert still keeps one row per idempotency key.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    business_date = date(2026, 6, 29)
    result = successful_item(item_key="employee-100")
    updated = successful_item(item_key="employee-100", details={"updated": True})

    db.upsert_item_result(result, "run-1", "orangehrm", business_date)
    db.upsert_item_result(updated, "run-2", "orangehrm", business_date)

    count = fetch_one(db, "SELECT COUNT(*) AS count FROM item_results")
    assert count["count"] == 1
    assert db.list_results_by_business_date("orangehrm", business_date) == [updated]


def test_find_stale_items_returns_only_old_in_progress_for_portal_and_date(
    tmp_path: Path,
) -> None:
    """Verify that find stale items returns only old in progress for portal and date.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    business_date = date(2026, 6, 29)
    old_stamp = utc_stamp(-600)
    fresh_stamp = utc_stamp(0)
    db.mark_item_in_progress(
        "run-old",
        "orangehrm",
        business_date,
        "old-in-progress",
        "sync_employee_state",
    )
    db.mark_item_in_progress(
        "run-fresh",
        "orangehrm",
        business_date,
        "fresh-in-progress",
        "sync_employee_state",
    )
    db.mark_item_in_progress(
        "run-other-date",
        "orangehrm",
        date(2026, 6, 28),
        "other-date",
        "sync_employee_state",
    )
    db.mark_item_in_progress(
        "run-other-portal",
        "saucedemo",
        business_date,
        "other-portal",
        "checkout",
    )
    db.upsert_item_result(
        successful_item(item_key="success-1"),
        "run-success",
        "orangehrm",
        business_date,
    )
    for key in ("old-in-progress", "other-date", "other-portal"):
        set_item_updated_at(db, key, old_stamp)
    set_item_updated_at(db, "fresh-in-progress", fresh_stamp)
    set_item_updated_at(db, "success-1", old_stamp)

    stale_items = db.find_stale_items("orangehrm", business_date, timeout_seconds=300)

    assert stale_items == [
        {
            "run_id": "run-old",
            "portal_name": "orangehrm",
            "business_date": "2026-06-29",
            "item_key": "old-in-progress",
            "operation": "sync_employee_state",
            "status": ItemStatus.IN_PROGRESS.value,
            "updated_at": old_stamp,
        }
    ]


def test_find_stale_runs_returns_only_old_unfinished_runs(tmp_path: Path) -> None:
    """Verify that find stale runs returns only old unfinished runs.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    old_stamp = utc_stamp(-600)
    fresh_stamp = utc_stamp(0)
    db.create_run("run-old", "orangehrm", date(2026, 6, 29))
    db.create_run("run-fresh", "orangehrm", date(2026, 6, 29))
    db.create_run("run-finished", "orangehrm", date(2026, 6, 29))
    db.finish_run("run-finished", RunStatus.SUCCESS, {"ok": True})
    set_run_updated_at(db, "run-old", old_stamp)
    set_run_updated_at(db, "run-fresh", fresh_stamp)
    set_run_updated_at(db, "run-finished", old_stamp)

    stale_runs = db.find_stale_runs(timeout_seconds=300)

    assert len(stale_runs) == 1
    assert stale_runs[0]["run_id"] == "run-old"
    assert stale_runs[0]["portal_name"] == "orangehrm"
    assert stale_runs[0]["business_date"] == "2026-06-29"
    assert stale_runs[0]["status"] == RunStatus.RUNNING.value
    assert stale_runs[0]["updated_at"] == old_stamp
    assert stale_runs[0]["started_at"]


def test_mark_run_stale_marks_only_eligible_old_unfinished_run(tmp_path: Path) -> None:
    """Verify that mark run stale marks only eligible old unfinished run.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    old_stamp = utc_stamp(-600)
    db.create_run("run-old", "orangehrm", date(2026, 6, 29))
    set_run_updated_at(db, "run-old", old_stamp)

    assert db.mark_run_stale("run-old", timeout_seconds=300) is True

    row = fetch_one(db, "SELECT * FROM runs WHERE run_id = ?", ("run-old",))
    assert row["status"] == RunStatus.STALE.value
    assert row["updated_at"] != old_stamp
    assert row["finished_at"] is None


def test_mark_run_stale_returns_false_for_fresh_finished_or_missing_runs(
    tmp_path: Path,
) -> None:
    """Verify that mark run stale returns false for fresh finished or missing runs.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    old_stamp = utc_stamp(-600)
    fresh_stamp = utc_stamp(0)
    db.create_run("run-fresh", "orangehrm", date(2026, 6, 29))
    db.create_run("run-finished", "orangehrm", date(2026, 6, 29))
    db.finish_run("run-finished", RunStatus.SUCCESS, {"ok": True})
    set_run_updated_at(db, "run-fresh", fresh_stamp)
    set_run_updated_at(db, "run-finished", old_stamp)

    assert db.mark_run_stale("run-fresh", timeout_seconds=300) is False
    assert db.mark_run_stale("run-finished", timeout_seconds=300) is False
    assert db.mark_run_stale("missing-run", timeout_seconds=300) is False

    fresh = fetch_one(db, "SELECT status FROM runs WHERE run_id = ?", ("run-fresh",))
    finished = fetch_one(db, "SELECT status FROM runs WHERE run_id = ?", ("run-finished",))
    assert fresh["status"] == RunStatus.RUNNING.value
    assert finished["status"] == RunStatus.SUCCESS.value


def test_mark_stale_item_failed_marks_only_old_in_progress_item(tmp_path: Path) -> None:
    """Verify that mark stale item failed marks only old in progress item.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    db = connector(tmp_path)
    business_date = date(2026, 6, 29)
    old_stamp = utc_stamp(-600)
    fresh_stamp = utc_stamp(0)
    db.mark_item_in_progress(
        "run-old",
        "orangehrm",
        business_date,
        "old-in-progress",
        "sync_employee_state",
    )
    db.mark_item_in_progress(
        "run-fresh",
        "orangehrm",
        business_date,
        "fresh-in-progress",
        "sync_employee_state",
    )
    db.upsert_item_result(
        successful_item(item_key="success-1"),
        "run-success",
        "orangehrm",
        business_date,
    )
    set_item_updated_at(db, "old-in-progress", old_stamp)
    set_item_updated_at(db, "fresh-in-progress", fresh_stamp)
    set_item_updated_at(db, "success-1", old_stamp)

    assert (
        db.mark_stale_item_failed(
            "run-old",
            "orangehrm",
            business_date,
            "old-in-progress",
            "sync_employee_state",
            timeout_seconds=300,
        )
        is True
    )
    assert (
        db.mark_stale_item_failed(
            "run-fresh",
            "orangehrm",
            business_date,
            "fresh-in-progress",
            "sync_employee_state",
            timeout_seconds=300,
        )
        is False
    )
    assert (
        db.mark_stale_item_failed(
            "run-success",
            "orangehrm",
            business_date,
            "success-1",
            "sync_employee_state",
            timeout_seconds=300,
        )
        is False
    )

    stale_row = fetch_one(
        db,
        "SELECT status, reason_code, error_detail FROM item_results WHERE item_key = ?",
        ("old-in-progress",),
    )
    fresh_row = fetch_one(
        db,
        "SELECT status, reason_code FROM item_results WHERE item_key = ?",
        ("fresh-in-progress",),
    )
    success_row = fetch_one(
        db,
        "SELECT status, reason_code FROM item_results WHERE item_key = ?",
        ("success-1",),
    )
    assert stale_row["status"] == ItemStatus.FAILED.value
    assert stale_row["reason_code"] == ReasonCode.SESSION_DROPPED.value
    assert "Recovered stale in-progress item" in stale_row["error_detail"]
    assert fresh_row["status"] == ItemStatus.IN_PROGRESS.value
    assert fresh_row["reason_code"] is None
    assert success_row["status"] == ItemStatus.SUCCESS.value
    assert success_row["reason_code"] is None


def test_insert_or_replace_does_not_appear_in_src() -> None:
    """Verify that insert or replace does not appear in src.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src").rglob("*.py")
        if "INSERT OR REPLACE" in path.read_text(encoding="utf-8")
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
