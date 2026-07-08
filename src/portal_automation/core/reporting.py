from datetime import date
from pathlib import Path
from typing import Any

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import ItemStatus, RunResult, RunStatus


class ReportGenerator:
    def __init__(self, artifacts: ArtifactStore, logger: Any | None = None) -> None:
        self.artifacts = artifacts
        self.logger = logger

    def render(self, result: RunResult) -> str:
        success_count = sum(1 for item in result.results if item.status is ItemStatus.SUCCESS)
        failure_count = sum(1 for item in result.results if item.status is ItemStatus.FAILED)
        lines = [
            f"Run ID: {result.run_id}",
            f"Portal: {result.portal_name}",
            f"Business date: {result.business_date.isoformat()}",
            f"Run status: {result.status.value}",
            f"Processed count: {len(result.results)}",
            f"Success count: {success_count}",
            f"Failure count: {failure_count}",
            "Items:",
        ]
        lines.extend(self._render_item(index, item) for index, item in enumerate(result.results, 1))
        return "\n".join(lines) + "\n"

    def write_report(self, result: RunResult) -> Path:
        path = self.artifacts.report_path(result.run_id)
        written_path = self.artifacts.write_text(path, self.render(result))
        if self.logger is not None and hasattr(self.logger, "info"):
            self.logger.info("report_generated", path=str(written_path))
        return written_path

    def generate_from_persistence(
        self,
        *,
        run_id: str,
        portal_name: str,
        business_date: date,
        status: RunStatus,
        persistence: Any,
    ) -> Path:
        results = persistence.list_results_by_business_date(portal_name, business_date)
        return self.write_report(
            RunResult(
                run_id=run_id,
                portal_name=portal_name,
                business_date=business_date,
                status=status,
                results=results,
            )
        )

    @staticmethod
    def _render_item(index: int, item: Any) -> str:
        reason_code = item.reason_code.value if item.reason_code is not None else ""
        artifact_path = item.artifact_path or ""
        return (
            f"{index}. item_key={item.item_key}; operation={item.operation}; "
            f"status={item.status.value}; reason_code={reason_code}; "
            f"artifact_path={artifact_path}; attempts={item.attempts}"
        )
