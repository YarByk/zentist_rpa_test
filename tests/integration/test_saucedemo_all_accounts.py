import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import ItemResult, ItemStatus, ReasonCode, RunContext, RunStatus
from portal_automation.core.observability import RunMetricsCollector, StructuredEventLogger
from portal_automation.core.persistence import PersistenceConnector
from portal_automation.core.reporting import ReportGenerator
from portal_automation.core.retries import PortalError
from portal_automation.portals.saucedemo import runner as runner_module
from portal_automation.portals.saucedemo.runner import SauceDemoRunner

BUSINESS_DATE = date(2026, 6, 29)
ALL_SAUCEDEMO_RECORDS = [
    ("standard_user", "Standard", "User", "10001"),
    ("locked_out_user", "Locked", "Out", "10002"),
    ("problem_user", "Problem", "User", "10003"),
    ("performance_glitch_user", "Performance", "Glitch", "10004"),
    ("error_user", "Error", "User", "10005"),
    ("visual_user", "Visual", "User", "10006"),
]


@dataclass
class ConfigStub:
    saucedemo_input_path: str
    saucedemo_password: str
    report_email_to: str | None = None


def write_all_accounts_input(tmp_path: Path) -> Path:
    """Write all accounts input.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = tmp_path / "saucedemo_accounts.json"
    path.write_text(
        json.dumps(
            [
                {
                    "account_key": username,
                    "username": username,
                    "items_to_add": 3,
                    "checkout_profile": {
                        "first_name": first_name,
                        "last_name": last_name,
                        "postal_code": postal_code,
                    },
                }
                for username, first_name, last_name, postal_code in ALL_SAUCEDEMO_RECORDS
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def make_context(tmp_path: Path, *, run_id: str = "saucedemo-all-accounts") -> RunContext:
    """Make context.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        run_id: Value supplied by the test or fixture for `run_id`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    metrics = RunMetricsCollector(
        artifacts,
        run_id=run_id,
        portal=SauceDemoRunner.portal_name,
        business_date=BUSINESS_DATE,
    )
    logger = StructuredEventLogger(
        artifacts,
        run_id=run_id,
        portal=SauceDemoRunner.portal_name,
        business_date=BUSINESS_DATE,
        metrics=metrics,
    )
    return RunContext(
        run_id=run_id,
        business_date=BUSINESS_DATE,
        dry_run=False,
        stale_item_timeout_seconds=300,
        config=ConfigStub(
            saucedemo_input_path=str(write_all_accounts_input(tmp_path)),
            saucedemo_password="secret_" + "sauce",
        ),
        persistence=PersistenceConnector(str(tmp_path / "portal.sqlite")),
        reporter=ReportGenerator(artifacts, logger=logger),
        logger=logger,
        metrics=metrics,
        artifacts=artifacts,
        email=object(),
    )


def fetch_rows(db_path: Path, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
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


def pre_finish_result(item_key: str) -> ItemResult:
    """Pre finish result.
    
    Args:
        item_key: Value supplied by the test or fixture for `item_key`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return ItemResult(
        item_key=item_key,
        operation=SauceDemoRunner.operation_name,
        status=ItemStatus.IN_PROGRESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
        details={
            "order_id": f"ord-{item_key}",
            "total": "$49.99",
            "order_details_captured_before_finish": True,
        },
    )


def success_result(item_key: str) -> ItemResult:
    """Success result.
    
    Args:
        item_key: Value supplied by the test or fixture for `item_key`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return ItemResult(
        item_key=item_key,
        operation=SauceDemoRunner.operation_name,
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
        details={"confirmation_text": "Thank you for your order!"},
    )


def test_saucedemo_all_accounts_continue_after_locked_out_and_downstream_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that saucedemo all accounts continue after locked out and downstream failure.
    
    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.
        monkeypatch: Value supplied by the test or fixture for `monkeypatch`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    context = make_context(tmp_path)
    processed: list[str] = []
    non_locked_login_successes: list[str] = []

    def fake_process_account(record, page_objects, run_context, *, persist_before_finish=None):
        """Fake process account.
        
        Args:
            record: Value supplied by the test or fixture for `record`.
            page_objects: Value supplied by the test or fixture for `page_objects`.
            run_context: Value supplied by the test or fixture for `run_context`.
            persist_before_finish: Value supplied by the test or fixture for
                `persist_before_finish`.
        
        Returns:
            None. The test communicates success through assertions.
        
        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        processed.append(record.account_key)
        if record.account_key == "locked_out_user":
            raise PortalError(ReasonCode.LOCKED_OUT, "user is locked out")

        non_locked_login_successes.append(record.account_key)
        if persist_before_finish is not None:
            persist_before_finish(pre_finish_result(record.account_key))

        if record.account_key == "error_user":
            raise PortalError(ReasonCode.CHECKOUT_FAILED, "downstream checkout failed")
        return success_result(record.account_key)

    monkeypatch.setattr(runner_module, "process_account", fake_process_account)

    result = SauceDemoRunner(pages_factory=lambda run_context: object()).run(context)

    expected_keys = [username for username, *_ in ALL_SAUCEDEMO_RECORDS]
    assert processed == expected_keys
    assert non_locked_login_successes == [
        "standard_user",
        "problem_user",
        "performance_glitch_user",
        "error_user",
        "visual_user",
    ]
    assert result.status is RunStatus.PARTIAL_SUCCESS
    assert len(result.results) == 6

    results_by_key = {item.item_key: item for item in result.results}
    assert results_by_key["standard_user"].status is ItemStatus.SUCCESS
    assert results_by_key["problem_user"].status is ItemStatus.SUCCESS
    assert results_by_key["performance_glitch_user"].status is ItemStatus.SUCCESS
    assert results_by_key["visual_user"].status is ItemStatus.SUCCESS
    assert results_by_key["locked_out_user"].status is ItemStatus.SKIPPED
    assert results_by_key["locked_out_user"].reason_code is ReasonCode.LOCKED_OUT
    assert results_by_key["locked_out_user"].details["expected_demo_failure"] is True
    assert results_by_key["error_user"].status is ItemStatus.FAILED
    assert results_by_key["error_user"].reason_code is ReasonCode.CHECKOUT_FAILED

    db_rows = fetch_rows(
        tmp_path / "portal.sqlite",
        """
        SELECT item_key, status, reason_code
        FROM item_results
        WHERE portal_name = ?
        ORDER BY id
        """,
        (SauceDemoRunner.portal_name,),
    )
    assert [row["item_key"] for row in db_rows] == expected_keys
    assert [row["status"] for row in db_rows].count(ItemStatus.SUCCESS.value) == 4
    assert [row["status"] for row in db_rows].count(ItemStatus.FAILED.value) == 1
    assert [row["status"] for row in db_rows].count(ItemStatus.SKIPPED.value) == 1

    report_path = tmp_path / "artifacts" / "runs" / context.run_id / "report.txt"
    report = report_path.read_text(encoding="utf-8")
    assert "Run status: partial_success" in report
    for key in expected_keys:
        assert f"item_key={key}" in report
    assert f"reason_code={ReasonCode.LOCKED_OUT.value}" in report
    assert f"reason_code={ReasonCode.CHECKOUT_FAILED.value}" in report

    events_path = tmp_path / "artifacts" / "runs" / context.run_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    item_started = [event for event in events if event["event"] == "item_started"]
    item_finished = [event for event in events if event["event"] == "item_finished"]
    item_failed = [event for event in events if event["event"] == "item_failed"]
    item_skipped = [event for event in events if event["event"] == "item_skipped"]
    operator_notices = [event for event in events if event["event"] == "operator_notice"]
    assert [event["item_key"] for event in item_started] == expected_keys
    assert {event["item_key"] for event in item_finished} == {
        "standard_user",
        "problem_user",
        "performance_glitch_user",
        "visual_user",
    }
    assert {event["item_key"] for event in item_failed} == {"error_user"}
    assert {event["item_key"] for event in item_skipped} == {"locked_out_user"}
    assert {event["item_key"] for event in operator_notices} == {"locked_out_user"}

    metrics_path = tmp_path / "artifacts" / "runs" / context.run_id / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert metrics["items_total"] == 6
    assert metrics["items_success"] == 4
    assert metrics["items_failed"] == 1
    assert metrics["items_skipped"] == 1

    artifact_text = "\n".join(
        [
            report,
            events_path.read_text(encoding="utf-8"),
            metrics_path.read_text(encoding="utf-8"),
        ]
    )
    assert "secret_sauce" not in artifact_text
    assert "secret_" + "sauce" not in artifact_text
