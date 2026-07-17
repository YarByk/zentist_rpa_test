import json
from datetime import date

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import ItemResult, ItemStatus
from portal_automation.core.observability import RunMetricsCollector, StructuredEventLogger


def test_structured_event_logger_creates_jsonl_with_required_fields_and_redacts_secrets(
    tmp_path,
) -> None:
    # Structured logs should preserve useful context while redacting secret-looking payload values.
    """Verify that structured event logger creates jsonl with required fields and redacts secrets.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    metrics = RunMetricsCollector(
        artifacts,
        run_id="run-1",
        portal="demo",
        business_date=date(2026, 6, 29),
    )
    logger = StructuredEventLogger(
        artifacts,
        run_id="run-1",
        portal="demo",
        business_date=date(2026, 6, 29),
        metrics=metrics,
    )

    logger.info(
        "email_failed",
        smtp_password="top-secret",
        orangehrm_password="portal-secret",
        nested={"token": "abc", "safe": "ok"},
    )
    logger.log_item_result(
        ItemResult(
            item_key="item-1",
            operation="op",
            status=ItemStatus.SUCCESS,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            attempts=1,
            details={},
        )
    )

    path = tmp_path / "artifacts" / "runs" / "run-1" / "events.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["email_failed", "item_finished"]
    for row in rows:
        assert row["run_id"] == "run-1"
        assert row["portal"] == "demo"
        assert row["business_date"] == "2026-06-29"
        assert row["timestamp"]
        assert row["event"]
    first = rows[0]
    assert first["smtp_password"] == "[REDACTED]"
    assert first["orangehrm_password"] == "[REDACTED]"
    assert first["nested"]["token"] == "[REDACTED]"
    assert first["nested"]["safe"] == "ok"
    text = path.read_text(encoding="utf-8")
    assert "top-secret" not in text
    assert "portal-secret" not in text
    assert '"abc"' not in text


def test_structured_event_logger_logs_skipped_items_with_specific_event(tmp_path) -> None:
    # Skipped items are operationally different from finished items and need their own event name.
    """Verify that structured event logger logs skipped items with specific event.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    logger = StructuredEventLogger(
        artifacts,
        run_id="run-1",
        portal="demo",
        business_date=date(2026, 6, 29),
    )

    logger.log_item_result(
        ItemResult(
            item_key="already-done",
            operation="op",
            status=ItemStatus.SKIPPED,
            reason_code=None,
            error_detail=None,
            artifact_path=None,
            attempts=0,
            details={},
        )
    )

    path = tmp_path / "artifacts" / "runs" / "run-1" / "events.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["event"] == "item_skipped"
    assert row["status"] == "skipped"
    assert row["item_key"] == "already-done"


def test_metrics_collector_writes_expected_json(tmp_path) -> None:
    # Metrics output should summarize item outcomes and retry count in one JSON payload.
    """Verify that metrics collector writes expected json.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    artifacts = ArtifactStore(str(tmp_path / "artifacts"))
    metrics = RunMetricsCollector(
        artifacts,
        run_id="run-1",
        portal="demo",
        business_date=date(2026, 6, 29),
    )
    metrics.increment_retry_count()
    metrics.record_run_result(
        type(
            "RunResultStub",
            (),
            {
                "results": [
                    ItemResult(
                        item_key="ok",
                        operation="op",
                        status=ItemStatus.SUCCESS,
                        reason_code=None,
                        error_detail=None,
                        artifact_path=None,
                        attempts=1,
                        details={},
                    ),
                    ItemResult(
                        item_key="bad",
                        operation="op",
                        status=ItemStatus.FAILED,
                        reason_code=None,
                        error_detail=None,
                        artifact_path=None,
                        attempts=1,
                        details={},
                    ),
                ]
            },
        )()
    )

    path = metrics.write_metrics()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-1"
    assert payload["portal"] == "demo"
    assert payload["business_date"] == "2026-06-29"
    assert payload["items_total"] == 2
    assert payload["items_success"] == 1
    assert payload["items_failed"] == 1
    assert payload["items_skipped"] == 0
    assert payload["retry_count"] == 1
    assert payload["duration_seconds"] >= 0
