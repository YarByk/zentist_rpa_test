import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import ItemResult, ItemStatus, RunResult

_SECRET_KEY_PARTS = ("password", "secret", "token", "credential")


def _utc_now() -> str:
    """Return the current UTC timestamp for structured output.

    Returns:
        ISO-8601 timestamp with microsecond precision.
    """
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _is_secret_key(key: str) -> bool:
    """Return whether a field name looks secret-bearing.

    Args:
        key: Field name to inspect.

    Returns:
        ``True`` when the key contains a configured secret-like substring.
    """
    lowered = key.lower()
    return any(secret in lowered for secret in _SECRET_KEY_PARTS)


def _sanitize_value(value: Any) -> Any:
    """Recursively redact values under secret-looking keys.

    Args:
        value: Arbitrary event field value.

    Returns:
        Sanitized value safe to write to event artifacts.
    """
    if isinstance(value, dict):
        # Redact nested secret-looking keys before anything reaches disk.
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
        """Create a collector for one run's summary metrics.

        Args:
            artifacts: Artifact store used to write ``metrics.json``.
            run_id: Unique run identifier.
            portal: Portal key.
            business_date: Business date for the run.
        """
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
        """Increment the retry counter by one."""
        self.retry_count += 1

    def record_run_result(self, result: RunResult) -> None:
        """Record item outcome counts from a run result.

        Args:
            result: Final run result whose item statuses should be counted.
        """
        self.items_total = len(result.results)
        self.items_success = sum(1 for item in result.results if item.status is ItemStatus.SUCCESS)
        self.items_failed = sum(1 for item in result.results if item.status is ItemStatus.FAILED)
        self.items_skipped = sum(1 for item in result.results if item.status is ItemStatus.SKIPPED)

    def write_metrics(self) -> Path:
        """Write the collected metrics artifact.

        Returns:
            Path to the written ``metrics.json`` file.

        Raises:
            OSError: If the metrics file cannot be written.
        """
        # Metrics are written at the end so duration captures the full run lifecycle.
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
        """Create a JSONL event logger for one run.

        Args:
            artifacts: Artifact store used to resolve ``events.jsonl``.
            run_id: Unique run identifier.
            portal: Portal key.
            business_date: Business date for the run.
            metrics: Optional metrics collector updated from retry events.
        """
        self.run_id = run_id
        self.portal = portal
        self.business_date = business_date
        self.metrics = metrics
        self._path = artifacts.run_dir(run_id) / "events.jsonl"

    def info(self, event: str, **kwargs: Any) -> None:
        """Write an informational event.

        Args:
            event: Event name.
            **kwargs: Additional event fields.

        Raises:
            OSError: If the event file cannot be written.
        """
        self._write_event(event, level="info", **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        """Write an error event.

        Args:
            event: Event name.
            **kwargs: Additional event fields.

        Raises:
            OSError: If the event file cannot be written.
        """
        self._write_event(event, level="error", **kwargs)

    def log_item_result(self, result: ItemResult) -> None:
        """Write a structured event for an item result.

        Args:
            result: Item result to summarize in the event stream.

        Raises:
            OSError: If the event file cannot be written.
        """
        if result.status is ItemStatus.FAILED:
            event = "item_failed"
        elif result.status is ItemStatus.SKIPPED:
            event = "item_skipped"
        else:
            event = "item_finished"
        self.info(
            event,
            item_key=result.item_key,
            operation=result.operation,
            status=result.status.value,
            reason_code=result.reason_code.value if result.reason_code is not None else None,
            attempts=result.attempts,
        )

    def _write_event(self, event: str, *, level: str, **kwargs: Any) -> None:
        """Append one sanitized event row to ``events.jsonl``.

        Args:
            event: Event name.
            level: Event severity label.
            **kwargs: Additional event fields.

        Raises:
            OSError: If the event file cannot be written.
        """
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
            # Retries are inferred from events so metrics stay decoupled from business code.
            self.metrics.increment_retry_count()
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
