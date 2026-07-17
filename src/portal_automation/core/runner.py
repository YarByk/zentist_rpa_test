from abc import ABC, abstractmethod
from typing import Any

from portal_automation.core.models import (
    ItemResult,
    ItemStatus,
    ReasonCode,
    RunContext,
    RunResult,
    RunStatus,
)
from portal_automation.core.retries import PortalError


class BasePortalRunnerZX(ABC):
    portal_name: str
    operation_name: str

    def run(self, context: RunContext) -> RunResult:
        """Execute the shared portal-run lifecycle.

        Args:
            context: Runtime context containing config, storage, artifacts, logging, and reporting.

        Returns:
            Final run result.

        Raises:
            PortalError: If loading or preflight fails with a portal-domain error.
            Exception: If loading, preflight, storage, or finalization raises unexpectedly.
        """
        logger = getattr(context, "logger", None)
        if logger is not None and hasattr(logger, "info"):
            logger.info("run_started", dry_run=context.dry_run)
        # Persist the run row before doing any work so crashes still leave a recoverable trace.
        context.persistence.create_run(context.run_id, self.portal_name, context.business_date)
        try:
            items = self.load_items(context)
        except PortalError as error:
            self._finish_failed_run(context, self._portal_error_result("__load_items__", error))
            raise
        except Exception as exc:
            self._finish_failed_run(
                context,
                self._unexpected_error_result("__load_items__", exc),
            )
            raise

        if context.dry_run:
            # Dry runs skip preflight, portal login, and item processing.
            # load_items() still runs so input validation errors surface before any portal work.
            results: list[ItemResult] = []
        else:
            try:
                self.preflight_check(context)
            except PortalError as error:
                self._finish_failed_run(context, self._portal_error_result("__preflight__", error))
                raise
            except Exception as exc:
                self._finish_failed_run(
                    context,
                    self._unexpected_error_result("__preflight__", exc),
                )
                raise
            committed_items = context.persistence.get_committed_items(
                self.portal_name,
                context.business_date,
            )
            skipped_committed_keys: set[str] = set()
            input_item_order: dict[str, int] = {}
            for item in items:
                item_key = self.item_key(item)
                input_item_order.setdefault(item_key, len(input_item_order))
                if item_key in committed_items:
                    # Successful same-day items are treated as already committed work.
                    skipped_committed_keys.add(item_key)
                    continue
                item_result = self._process_one_item(context, item, item_key)
                self._persist_item_result(context, item_result)
                if self._should_stop_item_iteration(context, item_result):
                    break
            # Re-read the rows owned by this run so the final report is not polluted by earlier
            # attempts for the same business date.
            if hasattr(context.persistence, "list_results_for_run"):
                results = context.persistence.list_results_for_run(context.run_id)
            else:
                results = context.persistence.list_results_by_business_date(
                    self.portal_name,
                    context.business_date,
                )
            if skipped_committed_keys:
                same_day_results = context.persistence.list_results_by_business_date(
                    self.portal_name,
                    context.business_date,
                )
                already_reported = {result.item_key for result in results}
                results.extend(
                    result
                    for result in same_day_results
                    if result.item_key in skipped_committed_keys
                    and result.item_key not in already_reported
                    and result.status is ItemStatus.SUCCESS
                )
            results.sort(
                key=lambda result: input_item_order.get(
                    result.item_key,
                    len(input_item_order),
                )
            )

        status = self._compute_status(results)
        result = RunResult(
            run_id=context.run_id,
            portal_name=self.portal_name,
            business_date=context.business_date,
            status=status,
            results=results,
        )
        self._finalize_and_finish(context, result)
        return result

    def item_key(self, item: Any) -> str:
        """Resolve the business key for one input item.

        Args:
            item: Input item object or dictionary.

        Returns:
            String key used for idempotency and reporting.
        """
        if isinstance(item, dict) and "item_key" in item:
            return str(item["item_key"])
        if hasattr(item, "item_key"):
            return str(item.item_key)
        return str(item)

    def _process_one_item(
        self,
        context: RunContext,
        item: Any,
        item_key: str,
    ) -> ItemResult:
        """Process one item and normalize item-level failures.

        Args:
            context: Runtime context.
            item: Input item to process.
            item_key: Business key for the item.

        Returns:
            Successful or failed item result.

        Raises:
            Exception: If writing the in-progress state or diagnostic logging fails critically.
        """
        try:
            logger = getattr(context, "logger", None)
            if logger is not None and hasattr(logger, "info"):
                logger.info(
                    "item_started",
                    item_key=item_key,
                    operation=self.operation_name,
                )
            context.persistence.mark_item_in_progress(
                context.run_id,
                self.portal_name,
                context.business_date,
                item_key,
                self.operation_name,
            )
            try:
                result = self.process_item(context, item)
            except PortalError as error:
                result = self._portal_error_result(item_key, error)
            except Exception as exc:
                result = self._unexpected_error_result(item_key, exc)
            if result.status is ItemStatus.FAILED:
                # Diagnostics are best-effort and should never hide the actual business failure.
                self._capture_failure_diagnostics(context, result)
            if logger is not None and hasattr(logger, "log_item_result"):
                logger.log_item_result(result)
            return result
        except Exception as exc:
            self._log_persistence_failure(context, exc)
            raise

    def _persist_item_result(self, context: RunContext, result: ItemResult) -> None:
        """Persist a completed item result.

        Args:
            context: Runtime context.
            result: Item result to persist.

        Raises:
            Exception: If the storage connector rejects the write.
        """
        try:
            context.persistence.upsert_item_result(
                result,
                context.run_id,
                self.portal_name,
                context.business_date,
            )
        except Exception as exc:
            self._log_persistence_failure(context, exc)
            raise

    def _portal_error_result(self, item_key: str, error: PortalError) -> ItemResult:
        """Convert a portal-domain error into a failed item result.

        Args:
            item_key: Business key for the failed item.
            error: Portal-domain error raised by a hook.

        Returns:
            Failed item result carrying the error reason and detail.
        """
        return ItemResult(
            item_key=item_key,
            operation=self.operation_name,
            status=ItemStatus.FAILED,
            reason_code=error.reason,
            error_detail=error.detail,
            artifact_path=None,
            attempts=error.attempts,
            details={},
        )

    def _unexpected_error_result(self, item_key: str, exc: Exception) -> ItemResult:
        """Convert an unexpected exception into a failed item result.

        Args:
            item_key: Business key for the failed item.
            exc: Unexpected exception raised by a hook.

        Returns:
            Failed item result with ``UNEXPECTED_ERROR``.
        """
        return ItemResult(
            item_key=item_key,
            operation=self.operation_name,
            status=ItemStatus.FAILED,
            reason_code=ReasonCode.UNEXPECTED_ERROR,
            error_detail=str(exc),
            artifact_path=None,
            attempts=1,
            details={},
        )

    def _compute_status(self, results: list[ItemResult]) -> RunStatus:
        """Compute the aggregate run status from item results.

        Args:
            results: Item results included in the run summary.

        Returns:
            ``SUCCESS``, ``FAILED``, or ``PARTIAL_SUCCESS``.
        """
        failed = sum(1 for result in results if result.status is ItemStatus.FAILED)
        if failed == 0:
            return RunStatus.SUCCESS
        if failed == len(results):
            return RunStatus.FAILED
        return RunStatus.PARTIAL_SUCCESS

    def _summary(self, results: list[ItemResult]) -> dict[str, int]:
        """Compute item status counts for persisted run summary JSON.

        Args:
            results: Item results included in the run summary.

        Returns:
            Dictionary with total, success, failed, and skipped counts.
        """
        return {
            "total": len(results),
            "success": sum(1 for result in results if result.status is ItemStatus.SUCCESS),
            "failed": sum(1 for result in results if result.status is ItemStatus.FAILED),
            "skipped": sum(1 for result in results if result.status is ItemStatus.SKIPPED),
        }

    def _finish_failed_run(self, context: RunContext, failure: ItemResult) -> None:
        """Finalize and persist a run that failed before item iteration completed.

        Args:
            context: Runtime context.
            failure: Synthetic item result describing the run-level failure.

        Raises:
            Exception: If finalization or storage update fails.
        """
        # Run-level failures are normalized into a synthetic item so reporting stays consistent.
        self._capture_failure_diagnostics(context, failure)
        result = RunResult(
            run_id=context.run_id,
            portal_name=self.portal_name,
            business_date=context.business_date,
            status=RunStatus.FAILED,
            results=[failure],
        )
        self._finalize_and_finish(context, result)

    def _finalize_and_finish(self, context: RunContext, result: RunResult) -> None:
        """Run finalization hooks and mark the run finished.

        Args:
            context: Runtime context.
            result: Final run result.

        Raises:
            Exception: If finalization, metrics writing, or storage update fails.
        """
        # Finalization writes reports and notifications before the run row is closed out.
        self.finalize(context, result)
        metrics = getattr(context, "metrics", None)
        if metrics is not None and hasattr(metrics, "record_run_result"):
            metrics.record_run_result(result)
        logger = getattr(context, "logger", None)
        if logger is not None and hasattr(logger, "info"):
            logger.info("run_finished", status=result.status.value)
        context.persistence.finish_run(context.run_id, result.status, self._summary(result.results))
        if metrics is not None and hasattr(metrics, "write_metrics"):
            metrics.write_metrics()

    def _capture_failure_diagnostics(self, context: RunContext, result: ItemResult) -> None:
        """Attach best-effort diagnostic artifact paths to a failed result.

        Args:
            context: Runtime context that may expose a diagnostics helper.
            result: Failed item result to enrich.
        """
        diagnostics = getattr(context, "diagnostics", None)
        if diagnostics is None or not hasattr(diagnostics, "capture_failure_artifacts"):
            return
        try:
            paths = diagnostics.capture_failure_artifacts(
                run_id=context.run_id,
                portal_name=self.portal_name,
                item_key=result.item_key,
                artifacts=context.artifacts,
            )
        except Exception as exc:
            logger = getattr(context, "logger", None)
            if logger is not None and hasattr(logger, "error"):
                try:
                    logger.error(
                        "failure_diagnostics_failed",
                        item_key=result.item_key,
                        error=str(exc),
                    )
                except Exception:
                    return
            return

        if not paths:
            return
        result.details = {**result.details, "diagnostics": paths}
        logger = getattr(context, "logger", None)
        if logger is not None and hasattr(logger, "info"):
            try:
                logger.info(
                    "failure_diagnostics_captured",
                    item_key=result.item_key,
                    **paths,
                )
            except Exception:
                return

    def _log_persistence_failure(self, context: RunContext, exc: Exception) -> None:
        """Log a best-effort storage failure event.

        Args:
            context: Runtime context that may expose a logger.
            exc: Exception raised by the storage connector.
        """
        logger = getattr(context, "logger", None)
        if logger is None or not hasattr(logger, "error"):
            return
        try:
            logger.error("persistence_failure", error=str(exc))
        except Exception:
            return

    def _should_stop_item_iteration(self, context: RunContext, result: ItemResult) -> bool:
        """Return whether the current run should stop before the next input item.

        Args:
            context: Runtime context.
            result: Most recently persisted item result.

        Returns:
            ``True`` when a portal-specific runner has detected a run-level condition that makes
            processing further items misleading or wasteful.
        """
        return False

    @abstractmethod
    def preflight_check(self, context: RunContext) -> None:
        """Validate runtime prerequisites before item processing.

        Args:
            context: Runtime context.

        Raises:
            PortalError: If portal-specific prerequisites are not satisfied.
        """
        raise RuntimeError("abstract hook must be implemented by portal runner")

    @abstractmethod
    def load_items(self, context: RunContext) -> list[Any]:
        """Load and validate input items for the run.

        Args:
            context: Runtime context.

        Returns:
            List of input items.

        Raises:
            PortalError: If input loading or validation fails.
        """
        raise RuntimeError("abstract hook must be implemented by portal runner")

    @abstractmethod
    def process_item(self, context: RunContext, item: Any) -> ItemResult:
        """Process one portal-specific item.

        Args:
            context: Runtime context.
            item: Input item to process.

        Returns:
            Item result for the processed item.

        Raises:
            PortalError: If the item fails with a known portal-domain reason.
        """
        raise RuntimeError("abstract hook must be implemented by portal runner")

    @abstractmethod
    def finalize(self, context: RunContext, result: RunResult) -> None:
        """Run portal-specific finalization after item processing.

        Args:
            context: Runtime context.
            result: Final run result.

        Raises:
            Exception: If reporting, notification, or cleanup fails.
        """
        raise RuntimeError("abstract hook must be implemented by portal runner")
