from collections.abc import Callable
from typing import Any

from portal_automation.core.models import ItemResult, ItemStatus, ReasonCode, RunContext, RunResult
from portal_automation.core.retries import PortalError
from portal_automation.core.runner import BasePortalRunnerZX
from portal_automation.portals.saucedemo.input_schema import (
    InputValidationError,
    load_account_records,
)
from portal_automation.portals.saucedemo.workflow import (
    SauceDemoWorkflowPages,
    process_account,
)

EXPECTED_DEMO_FAILURE_NOTICES: dict[str, dict[ReasonCode, str]] = {
    "locked_out_user": {
        ReasonCode.LOCKED_OUT: (
            "Sauce Demo intentionally keeps this demo account locked. "
            "The account was reported to the operator and skipped so the remaining "
            "accounts can run."
        ),
    },
    "problem_user": {
        ReasonCode.VALIDATION_FAILED: (
            "Sauce Demo intentionally makes this demo account behave inconsistently "
            "during checkout. The account was reported to the operator and skipped so "
            "the remaining accounts can run."
        ),
    },
    "error_user": {
        ReasonCode.VALIDATION_FAILED: (
            "Sauce Demo intentionally makes this demo account fail cart or checkout validation. "
            "The account was reported to the operator and skipped so the remaining "
            "accounts can run."
        ),
    },
}


class SauceDemoRunner(BasePortalRunnerZX):
    portal_name = "saucedemo"
    operation_name = "checkout"

    def __init__(
        self,
        pages_factory: Callable[[RunContext], SauceDemoWorkflowPages] | None = None,
    ) -> None:
        """Create a Sauce Demo runner.

        Args:
            pages_factory: Optional factory that creates the workflow page adapter for live runs.
        """
        self._pages_factory = pages_factory
        self._pre_finish_details_by_item: dict[str, dict[str, Any]] = {}

    def preflight_check(self, context: RunContext) -> None:
        """Validate Sauce Demo live-run prerequisites.

        Args:
            context: Runtime context.

        Raises:
            PortalError: If the Sauce Demo password is missing or blank.
        """
        password = getattr(context.config, "saucedemo_password", None)
        if not isinstance(password, str) or not password.strip():
            raise PortalError(
                ReasonCode.CREDENTIAL_EXPIRED,
                "Sauce Demo password is not configured.",
            )

    def load_items(self, context: RunContext) -> list[Any]:
        """Load Sauce Demo account input records.

        Args:
            context: Runtime context with ``config.saucedemo_input_path``.

        Returns:
            Validated account records.

        Raises:
            PortalError: If input validation fails.
        """
        try:
            return load_account_records(context.config.saucedemo_input_path)
        except InputValidationError as exc:
            raise PortalError(ReasonCode.INPUT_VALIDATION_FAILED, str(exc)) from exc

    def item_key(self, item: Any) -> str:
        """Return the account key for a Sauce Demo input item.

        Args:
            item: Account record or fallback item.

        Returns:
            Account key string.
        """
        if hasattr(item, "account_key"):
            return str(item.account_key)
        return super().item_key(item)

    def process_item(self, context: RunContext, item: Any) -> ItemResult:
        """Process one Sauce Demo account checkout.

        Args:
            context: Runtime context.
            item: Account record to process.

        Returns:
            Item result from ``process_account``.

        Raises:
            PortalError: If the page factory is missing or checkout fails with a portal-domain
                reason.
        """
        item_key = self.item_key(item)
        self._pre_finish_details_by_item.pop(item_key, None)
        if self._pages_factory is None:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "Sauce Demo page factory is not configured.",
            )

        def persist_before_finish(result: ItemResult) -> None:
            """Persist captured checkout details before the final finish action.

            Args:
                result: In-progress item result produced by the workflow.

            Raises:
                Exception: If the storage connector rejects the write.
            """
            # Persist checkout details before the final click so partial progress is not lost.
            context.persistence.upsert_item_result(
                result,
                context.run_id,
                self.portal_name,
                context.business_date,
            )
            self._pre_finish_details_by_item[result.item_key] = dict(result.details)

        return process_account(
            item,
            self._pages_factory(context),
            context,
            persist_before_finish=persist_before_finish,
        )

    def _portal_error_result(self, item_key: str, error: PortalError) -> ItemResult:
        """Convert a portal error into an item result with Sauce Demo demo-defect handling.

        Args:
            item_key: Account key associated with the failure.
            error: Portal-domain failure.

        Returns:
            Failed item result, or a skipped result for known intentionally broken Sauce Demo demo
            users.
        """
        result = super()._portal_error_result(item_key, error)
        pre_finish_details = self._pre_finish_details_by_item.get(item_key)
        if pre_finish_details is not None:
            # Preserve any order details captured before the failure occurred.
            result.details = {
                **pre_finish_details,
                "failed_after_pre_finish_persist": True,
            }
        notice = _expected_demo_failure_notice(item_key, error.reason)
        if notice is not None:
            # Known Sauce Demo defect accounts should be visible to the operator, but they should
            # not turn the whole live demonstration into a failed run.
            result.status = ItemStatus.SKIPPED
            result.error_detail = notice
            result.details = {
                **result.details,
                "expected_demo_failure": True,
                "operator_notice": notice,
            }
        return result

    def finalize(self, context: RunContext, result: RunResult) -> None:
        """Write report artifacts and send the Sauce Demo run notification.

        Args:
            context: Runtime context.
            result: Final run result.

        Raises:
            Exception: If report writing or email delivery fails.
        """
        run_id = getattr(context, "run_id", result.run_id)
        self._log_operator_notices(context, result)
        report_path = None
        if hasattr(context.reporter, "write_report"):
            report_path = context.reporter.write_report(result)
        email = getattr(context, "email", None)
        if hasattr(email, "send_report"):
            body = (
                context.reporter.render(result)
                if hasattr(context.reporter, "render")
                else f"Portal run {run_id} completed with status {result.status.value}."
            )
            email.send_report(
                run_id=run_id,
                to=getattr(context.config, "report_email_to", None),
                subject=f"SauceDemo run report: {run_id}",
                body=body,
                report_path=report_path,
            )

    def _log_operator_notices(self, context: RunContext, result: RunResult) -> None:
        """Emit explicit operator-facing notices for known skipped demo accounts.

        Args:
            context: Runtime context that may expose a structured logger.
            result: Final run result whose skipped items should be inspected.

        Raises:
            OSError: If the configured logger cannot write an event.
        """
        logger = getattr(context, "logger", None)
        for item in result.results:
            notice = item.details.get("operator_notice")
            if not notice:
                continue
            print(f"operator_notice: item_key={item.item_key}; {notice}")
            if logger is not None and hasattr(logger, "info"):
                logger.info(
                    "operator_notice",
                    item_key=item.item_key,
                    status=item.status.value,
                    reason_code=item.reason_code.value if item.reason_code is not None else None,
                    message=notice,
                )


def _expected_demo_failure_notice(item_key: str, reason: ReasonCode) -> str | None:
    """Return the operator notice for a known intentionally broken Sauce Demo account.

    Args:
        item_key: Sauce Demo account key.
        reason: Portal-domain reason raised by the workflow.

    Returns:
        Human-readable notice when the account and reason pair is an expected demo defect,
        otherwise ``None``.
    """
    return EXPECTED_DEMO_FAILURE_NOTICES.get(item_key, {}).get(reason)
