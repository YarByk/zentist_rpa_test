import json
from datetime import date

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import ItemResult, ItemStatus
from portal_automation.core.observability import RunMetricsCollector, StructuredEventLogger


def test_structured_event_logger_creates_jsonl_with_required_fields_and_redacts_secrets(
    tmp_path,
) -> None:
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


def test_metrics_collector_writes_expected_json(tmp_path) -> None:
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
