from datetime import date
from pathlib import Path
from typing import Any

from portal_automation.core.artifact_store import ArtifactStore
from portal_automation.core.models import ItemStatus, RunResult, RunStatus

SAFE_DETAIL_KEYS = frozenset(
    {
        "created_employee",
        "job_updated",
        "salary_document_uploaded",
        "created",
        "order_completed",
        "cart_count",
        "confirmation_text",
        "diagnostics",
        "expected_demo_failure",
        "item_names",
        "items_requested",
        "operator_notice",
        "subtotal",
        "tax",
        "total",
    }
)


class ReportGenerator:
    def __init__(self, artifacts: ArtifactStore, logger: Any | None = None) -> None:
        """Create a report generator.

        Args:
            artifacts: Artifact store used to resolve report paths.
            logger: Optional structured logger for report generation events.
        """
        self.artifacts = artifacts
        self.logger = logger

    def render(self, result: RunResult) -> str:
        """Render a run result as reviewer-facing plain text.

        Args:
            result: Completed run result to summarize.

        Returns:
            Plain-text report ending with one newline.
        """
        # Reports stay plain text on purpose so they are easy to inspect in artifacts and email.
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
        """Write a rendered report to the run artifact directory.

        Args:
            result: Completed run result to write.

        Returns:
            Path to the written report.

        Raises:
            OSError: If the report artifact cannot be written.
        """
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
        """Generate a report from persisted business-date results.

        Args:
            run_id: Run identifier to use for the generated report artifact.
            portal_name: Portal key whose persisted results should be loaded.
            business_date: Business date for the result query.
            status: Run status to display in the generated report.
            persistence: Object exposing ``list_results_by_business_date``.

        Returns:
            Path to the written report.

        Raises:
            OSError: If the report artifact cannot be written.
        """
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
        """Render one item result as a single report line.

        Args:
            index: One-based item index in report order.
            item: Object with item result attributes.

        Returns:
            Plain-text item summary line.
        """
        reason_code = item.reason_code.value if item.reason_code is not None else ""
        artifact_path = item.artifact_path or ""
        details = ReportGenerator._render_details(getattr(item, "details", {}))
        return (
            f"{index}. item_key={item.item_key}; operation={item.operation}; "
            f"status={item.status.value}; reason_code={reason_code}; "
            f"artifact_path={artifact_path}; attempts={item.attempts}; details={details}"
        )

    @staticmethod
    def _render_details(details: Any) -> str:
        """Render item details as stable key-value text.

        Args:
            details: Item details mapping.

        Returns:
            Semicolon-separated key-value text, or an empty string.
        """
        if not isinstance(details, dict) or not details:
            return ""
        safe_items = [
            (key, value)
            for key, value in sorted(details.items())
            if key in SAFE_DETAIL_KEYS
        ]
        return ", ".join(f"{key}={value}" for key, value in safe_items)
