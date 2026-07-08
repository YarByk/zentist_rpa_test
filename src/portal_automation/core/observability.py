import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import ItemResult, ItemStatus, RunResult

_SECRET_KEY_PARTS = ("password", "secret", "token", "credential")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(secret in lowered for secret in _SECRET_KEY_PARTS)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[REDACTED]" if _is_secret_key(key) else _sanitize_value(inner))
            for key, inner in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    return value


class RunMetricsCollector:
    def __init__(
        self,
        artifacts: ArtifactStore,
        *,
        run_id: str,
        portal: str,
        business_date: date,
    ) -> None:
        self.artifacts = artifacts
        self.run_id = run_id
        self.portal = portal
        self.business_date = business_date
        self.retry_count = 0
        self.items_total = 0
        self.items_success = 0
        self.items_failed = 0
        self.items_skipped = 0
        self._started = time.perf_counter()

    def increment_retry_count(self) -> None:
        self.retry_count += 1

    def record_run_result(self, result: RunResult) -> None:
        self.items_total = len(result.results)
        self.items_success = sum(1 for item in result.results if item.status is ItemStatus.SUCCESS)
        self.items_failed = sum(1 for item in result.results if item.status is ItemStatus.FAILED)
        self.items_skipped = sum(1 for item in result.results if item.status is ItemStatus.SKIPPED)

    def write_metrics(self) -> Path:
        payload = {
            "run_id": self.run_id,
            "portal": self.portal,
            "business_date": self.business_date.isoformat(),
            "items_total": self.items_total,
            "items_success": self.items_success,
            "items_failed": self.items_failed,
            "items_skipped": self.items_skipped,
            "retry_count": self.retry_count,
            "duration_seconds": round(time.perf_counter() - self._started, 6),
        }
        path = self.artifacts.run_dir(self.run_id) / "metrics.json"
        path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return path


class StructuredEventLogger:
    def __init__(
        self,
        artifacts: ArtifactStore,
        *,
        run_id: str,
        portal: str,
        business_date: date,
        metrics: RunMetricsCollector | None = None,
    ) -> None:
        self.run_id = run_id
        self.portal = portal
        self.business_date = business_date
        self.metrics = metrics
        self._path = artifacts.run_dir(run_id) / "events.jsonl"

    def info(self, event: str, **kwargs: Any) -> None:
        self._write_event(event, level="info", **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._write_event(event, level="error", **kwargs)

    def log_item_result(self, result: ItemResult) -> None:
        event = "item_failed" if result.status is ItemStatus.FAILED else "item_finished"
        self.info(
            event,
            item_key=result.item_key,
            operation=result.operation,
            status=result.status.value,
            reason_code=result.reason_code.value if result.reason_code is not None else None,
            attempts=result.attempts,
        )

    def _write_event(self, event: str, *, level: str, **kwargs: Any) -> None:
        payload = {
            "run_id": self.run_id,
            "portal": self.portal,
            "business_date": self.business_date.isoformat(),
            "timestamp": _utc_now(),
            "event": event,
            "level": level,
        }
        payload.update(_sanitize_value(kwargs))
        if event == "retry_attempt" and self.metrics is not None:
            self.metrics.increment_retry_count()
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
