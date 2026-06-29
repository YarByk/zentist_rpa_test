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
            for item in items:
                item_key = self.item_key(item)
                if item_key in committed_items:
                    continue
                item_result = self._process_one_item(context, item, item_key)
                self._persist_item_result(context, item_result)
            results = context.persistence.list_results_by_business_date(
                self.portal_name,
                context.business_date,
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
        try:
            context.persistence.mark_item_in_progress(
                context.run_id,
                self.portal_name,
                context.business_date,
                item_key,
                self.operation_name,
            )
            try:
                return self.process_item(context, item)
            except PortalError as error:
                return self._portal_error_result(item_key, error)
            except Exception as exc:
                return self._unexpected_error_result(item_key, exc)
        except Exception as exc:
            self._log_persistence_failure(context, exc)
            raise

    def _persist_item_result(self, context: RunContext, result: ItemResult) -> None:
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
        failed = sum(1 for result in results if result.status is ItemStatus.FAILED)
        if failed == 0:
            return RunStatus.SUCCESS
        if failed == len(results):
            return RunStatus.FAILED
        return RunStatus.PARTIAL_SUCCESS

    def _summary(self, results: list[ItemResult]) -> dict[str, int]:
        return {
            "total": len(results),
            "success": sum(1 for result in results if result.status is ItemStatus.SUCCESS),
            "failed": sum(1 for result in results if result.status is ItemStatus.FAILED),
            "skipped": sum(1 for result in results if result.status is ItemStatus.SKIPPED),
        }

    def _finish_failed_run(self, context: RunContext, failure: ItemResult) -> None:
        result = RunResult(
            run_id=context.run_id,
            portal_name=self.portal_name,
            business_date=context.business_date,
            status=RunStatus.FAILED,
            results=[failure],
        )
        self._finalize_and_finish(context, result)

    def _finalize_and_finish(self, context: RunContext, result: RunResult) -> None:
        self.finalize(context, result)
        context.persistence.finish_run(context.run_id, result.status, self._summary(result.results))

    def _log_persistence_failure(self, context: RunContext, exc: Exception) -> None:
        logger = getattr(context, "logger", None)
        if logger is None or not hasattr(logger, "error"):
            return
        try:
            logger.error("persistence_failure", error=str(exc))
        except Exception:
            return

    @abstractmethod
    def preflight_check(self, context: RunContext) -> None:
        raise RuntimeError("abstract hook must be implemented by portal runner")

    @abstractmethod
    def load_items(self, context: RunContext) -> list[Any]:
        raise RuntimeError("abstract hook must be implemented by portal runner")

    @abstractmethod
    def process_item(self, context: RunContext, item: Any) -> ItemResult:
        raise RuntimeError("abstract hook must be implemented by portal runner")

    @abstractmethod
    def finalize(self, context: RunContext, result: RunResult) -> None:
        raise RuntimeError("abstract hook must be implemented by portal runner")
