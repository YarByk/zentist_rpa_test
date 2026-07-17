import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from portal_automation.core.models import ItemResult, ItemStatus, ReasonCode, RunStatus


def _utc_now() -> str:
    """Return the current UTC timestamp for database rows.

    Returns:
        ISO-8601 timestamp with microsecond precision.
    """
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _json_dumps(value: dict[str, Any]) -> str:
    """Serialize a dictionary with stable key ordering.

    Args:
        value: Dictionary to serialize.

    Returns:
        JSON string with sorted keys.
    """
    return json.dumps(value, sort_keys=True)


def _stale_cutoff(timeout_seconds: int) -> str:
    """Return the timestamp before which rows are considered stale.

    Args:
        timeout_seconds: Age threshold in seconds.

    Returns:
        ISO-8601 cutoff timestamp.
    """
    return (datetime.now(UTC) - timedelta(seconds=timeout_seconds)).isoformat(
        timespec="microseconds"
    )


class PersistenceConnector:
    def __init__(self, db_path: str) -> None:
        """Open a SQLite database and initialize the schema.

        Args:
            db_path: Path to the SQLite database file.

        Raises:
            sqlite3.Error: If the database cannot be opened or initialized.
            OSError: If the parent directory cannot be created.
        """
        self.db_path = db_path
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Create required tables when they do not already exist.

        Raises:
            sqlite3.Error: If schema creation fails.
        """
        # The schema is created lazily so a fresh workspace can run without any manual setup.
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                portal_name TEXT NOT NULL,
                business_date TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT,
                summary_json TEXT
            );
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS item_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                portal_name TEXT NOT NULL,
                business_date TEXT NOT NULL,
                item_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                reason_code TEXT,
                error_detail TEXT,
                attempts INTEGER NOT NULL DEFAULT 1,
                artifact_path TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (business_date, portal_name, item_key, operation)
            );
            """
        )
        self._connection.commit()

    def create_run(self, run_id: str, portal_name: str, business_date: date) -> None:
        """Insert a new running run row.

        Args:
            run_id: Unique run identifier.
            portal_name: Portal key.
            business_date: Business date for idempotency and reporting.

        Raises:
            sqlite3.Error: If the insert fails.
        """
        now = _utc_now()
        self._connection.execute(
            """
            INSERT INTO runs (
                run_id,
                portal_name,
                business_date,
                status,
                started_at,
                updated_at,
                finished_at,
                summary_json
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL);
            """,
            (
                run_id,
                portal_name,
                business_date.isoformat(),
                RunStatus.RUNNING.value,
                now,
                now,
            ),
        )
        self._connection.commit()

    def finish_run(self, run_id: str, status: RunStatus, summary: dict[str, Any]) -> None:
        """Mark a run finished and store its summary.

        Args:
            run_id: Unique run identifier.
            status: Final run status.
            summary: Run summary payload serialized as JSON.

        Raises:
            sqlite3.Error: If the update fails.
        """
        now = _utc_now()
        self._connection.execute(
            """
            UPDATE runs
            SET status = ?,
                finished_at = ?,
                updated_at = ?,
                summary_json = ?
            WHERE run_id = ?;
            """,
            (status.value, now, now, _json_dumps(summary), run_id),
        )
        self._connection.commit()

    def mark_run_stale(self, run_id: str, timeout_seconds: int) -> bool:
        """Mark an unfinished run as stale if it has not been updated within the timeout window.

        Args:
            run_id: Unique run identifier.
            timeout_seconds: Minimum age required before the run can be marked stale.

        Returns:
            ``True`` when a row was updated, otherwise ``False``.

        Raises:
            sqlite3.Error: If the update fails.
        """
        now = _utc_now()
        cursor = self._connection.execute(
            """
            UPDATE runs
            SET status = ?,
                updated_at = ?
            WHERE run_id = ?
              AND finished_at IS NULL
              AND updated_at < ?;
            """,
            (RunStatus.STALE.value, now, run_id, _stale_cutoff(timeout_seconds)),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def mark_stale_item_failed(
        self,
        run_id: str,
        portal_name: str,
        business_date: date,
        item_key: str,
        operation: str,
        timeout_seconds: int,
        *,
        reason_code: ReasonCode = ReasonCode.SESSION_DROPPED,
        error_detail: str = "Recovered stale in-progress item via CLI recover command.",
    ) -> bool:
        """Mark a stale in-progress item as failed.

        Args:
            run_id: Run that currently owns the stale item row.
            portal_name: Portal key.
            business_date: Business date for the idempotency key.
            item_key: Business item key.
            operation: Operation name for the item result.
            timeout_seconds: Minimum age required before the item can be marked failed.
            reason_code: Failure reason to store.
            error_detail: Failure detail to store.

        Returns:
            ``True`` when a row was updated, otherwise ``False``.

        Raises:
            sqlite3.Error: If the update fails.
        """
        now = _utc_now()
        cursor = self._connection.execute(
            """
            UPDATE item_results
            SET status = ?,
                reason_code = ?,
                error_detail = ?,
                updated_at = ?
            WHERE run_id = ?
              AND portal_name = ?
              AND business_date = ?
              AND item_key = ?
              AND operation = ?
              AND status = ?
              AND updated_at < ?;
            """,
            (
                ItemStatus.FAILED.value,
                reason_code.value,
                error_detail,
                now,
                run_id,
                portal_name,
                business_date.isoformat(),
                item_key,
                operation,
                ItemStatus.IN_PROGRESS.value,
                _stale_cutoff(timeout_seconds),
            ),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def mark_item_in_progress(
        self,
        run_id: str,
        portal_name: str,
        business_date: date,
        item_key: str,
        operation: str,
    ) -> None:
        """Insert or reclaim an in-progress item row.

        Args:
            run_id: Run currently processing the item.
            portal_name: Portal key.
            business_date: Business date for the idempotency key.
            item_key: Business item key.
            operation: Operation name for this item.

        Raises:
            sqlite3.Error: If the upsert fails.
        """
        now = _utc_now()
        # Upsert lets reruns reclaim stale or partially written work for the same business key.
        # attempts resets to 1 on conflict: each new run starts a fresh attempt count.
        self._connection.execute(
            """
            INSERT INTO item_results (
                run_id,
                portal_name,
                business_date,
                item_key,
                operation,
                status,
                reason_code,
                error_detail,
                attempts,
                artifact_path,
                details_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 1, NULL, ?, ?, ?)
            ON CONFLICT (business_date, portal_name, item_key, operation)
            DO UPDATE SET
                run_id = excluded.run_id,
                status = excluded.status,
                reason_code = NULL,
                error_detail = NULL,
                attempts = 1,
                artifact_path = NULL,
                details_json = excluded.details_json,
                updated_at = excluded.updated_at;
            """,
            (
                run_id,
                portal_name,
                business_date.isoformat(),
                item_key,
                operation,
                ItemStatus.IN_PROGRESS.value,
                "{}",
                now,
                now,
            ),
        )
        self._connection.commit()

    def upsert_item_result(
        self,
        result: ItemResult,
        run_id: str,
        portal_name: str,
        business_date: date,
    ) -> None:
        """Insert or update a final item result.

        Args:
            result: Item result to persist.
            run_id: Run currently owning the result.
            portal_name: Portal key.
            business_date: Business date for the idempotency key.

        Raises:
            sqlite3.Error: If the upsert fails.
        """
        now = _utc_now()
        # Results are keyed by business date + portal + item + operation for idempotent reruns.
        self._connection.execute(
            """
            INSERT INTO item_results (
                run_id,
                portal_name,
                business_date,
                item_key,
                operation,
                status,
                reason_code,
                error_detail,
                attempts,
                artifact_path,
                details_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (business_date, portal_name, item_key, operation)
            DO UPDATE SET
                run_id = excluded.run_id,
                status = excluded.status,
                reason_code = excluded.reason_code,
                error_detail = excluded.error_detail,
                attempts = excluded.attempts,
                artifact_path = excluded.artifact_path,
                details_json = excluded.details_json,
                updated_at = excluded.updated_at;
            """,
            (
                run_id,
                portal_name,
                business_date.isoformat(),
                result.item_key,
                result.operation,
                result.status.value,
                result.reason_code.value if result.reason_code is not None else None,
                result.error_detail,
                result.attempts,
                result.artifact_path,
                _json_dumps(result.details),
                now,
                now,
            ),
        )
        self._connection.commit()

    def list_results_for_run(self, run_id: str) -> list[ItemResult]:
        """Return persisted item results owned by one run.

        Args:
            run_id: Unique run identifier.

        Returns:
            Item results ordered by database insertion id.

        Raises:
            sqlite3.Error: If the query fails.
            ValueError: If persisted enum values are invalid.
            json.JSONDecodeError: If stored details JSON is invalid.
        """
        rows = self._connection.execute(
            """
            SELECT item_key,
                   operation,
                   status,
                   reason_code,
                   error_detail,
                   artifact_path,
                   attempts,
                   details_json
            FROM item_results
            WHERE run_id = ?
            ORDER BY id;
            """,
            (run_id,),
        ).fetchall()

        return self._rows_to_item_results(rows)

    def list_results_by_business_date(
        self,
        portal_name: str,
        business_date: date,
    ) -> list[ItemResult]:
        """Return persisted results for a portal and business date.

        Args:
            portal_name: Portal key.
            business_date: Business date to query.

        Returns:
            Item results ordered by database insertion id.

        Raises:
            sqlite3.Error: If the query fails.
            ValueError: If persisted enum values are invalid.
            json.JSONDecodeError: If stored details JSON is invalid.
        """
        rows = self._connection.execute(
            """
            SELECT item_key,
                   operation,
                   status,
                   reason_code,
                   error_detail,
                   artifact_path,
                   attempts,
                   details_json
            FROM item_results
            WHERE portal_name = ?
              AND business_date = ?
            ORDER BY id;
            """,
            (portal_name, business_date.isoformat()),
        ).fetchall()

        return self._rows_to_item_results(rows)

    def get_committed_items(self, portal_name: str, business_date: date) -> set[str]:
        """Return item keys already committed successfully for a business date.

        Args:
            portal_name: Portal key.
            business_date: Business date to query.

        Returns:
            Set of successful item keys.

        Raises:
            sqlite3.Error: If the query fails.
        """
        rows = self._connection.execute(
            """
            SELECT item_key
            FROM item_results
            WHERE portal_name = ?
              AND business_date = ?
              AND status = ?;
            """,
            (portal_name, business_date.isoformat(), ItemStatus.SUCCESS.value),
        ).fetchall()

        return {row["item_key"] for row in rows}

    def find_stale_items(
        self,
        portal_name: str,
        business_date: date,
        timeout_seconds: int,
    ) -> list[dict[str, Any]]:
        """Find stale in-progress item rows for recovery.

        Args:
            portal_name: Portal key.
            business_date: Business date to query.
            timeout_seconds: Age threshold in seconds.

        Returns:
            List of row dictionaries ordered by oldest update first.

        Raises:
            sqlite3.Error: If the query fails.
        """
        rows = self._connection.execute(
            """
            SELECT run_id,
                   portal_name,
                   business_date,
                   item_key,
                   operation,
                   status,
                   updated_at
            FROM item_results
            WHERE portal_name = ?
              AND business_date = ?
              AND status = ?
              AND updated_at < ?
            ORDER BY updated_at, id;
            """,
            (
                portal_name,
                business_date.isoformat(),
                ItemStatus.IN_PROGRESS.value,
                _stale_cutoff(timeout_seconds),
            ),
        ).fetchall()

        return [dict(row) for row in rows]

    def find_stale_runs(self, timeout_seconds: int) -> list[dict[str, Any]]:
        """Find unfinished runs older than the stale threshold.

        Args:
            timeout_seconds: Age threshold in seconds.

        Returns:
            List of row dictionaries ordered by oldest update first.

        Raises:
            sqlite3.Error: If the query fails.
        """
        rows = self._connection.execute(
            """
            SELECT run_id,
                   portal_name,
                   business_date,
                   status,
                   updated_at,
                   started_at
            FROM runs
            WHERE finished_at IS NULL
              AND updated_at < ?
            ORDER BY updated_at, run_id;
            """,
            (_stale_cutoff(timeout_seconds),),
        ).fetchall()

        return [dict(row) for row in rows]

    def _rows_to_item_results(self, rows: list[sqlite3.Row]) -> list[ItemResult]:
        """Convert SQLite rows into ``ItemResult`` objects.

        Args:
            rows: SQLite rows from an item result query.

        Returns:
            Converted item results.

        Raises:
            ValueError: If persisted enum values are invalid.
            json.JSONDecodeError: If stored details JSON is invalid.
        """
        return [
            ItemResult(
                item_key=row["item_key"],
                operation=row["operation"],
                status=ItemStatus(row["status"]),
                reason_code=ReasonCode(row["reason_code"]) if row["reason_code"] else None,
                error_detail=row["error_detail"],
                artifact_path=row["artifact_path"],
                attempts=row["attempts"],
                details=json.loads(row["details_json"] or "{}"),
            )
            for row in rows
        ]
