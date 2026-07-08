from collections.abc import Callable
from typing import Any

from portal_automation.core.models import ItemResult, ReasonCode, RunContext, RunResult
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


class SauceDemoRunner(BasePortalRunnerZX):
    portal_name = "saucedemo"
    operation_name = "checkout"
    max_sessions_per_account = 1

    def __init__(
        self,
        pages_factory: Callable[[RunContext], SauceDemoWorkflowPages] | None = None,
    ) -> None:
        self._pages_factory = pages_factory

    def preflight_check(self, context: RunContext) -> None:
        password = getattr(context.config, "saucedemo_password", None)
        if not isinstance(password, str) or not password.strip():
            raise PortalError(
                ReasonCode.CREDENTIAL_EXPIRED,
                "Sauce Demo password is not configured.",
            )

    def load_items(self, context: RunContext) -> list[Any]:
        try:
            return load_account_records(context.config.saucedemo_input_path)
        except InputValidationError as exc:
            raise PortalError(ReasonCode.INPUT_VALIDATION_FAILED, str(exc)) from exc

    def item_key(self, item: Any) -> str:
        if hasattr(item, "account_key"):
            return str(item.account_key)
        return super().item_key(item)

    def process_item(self, context: RunContext, item: Any) -> ItemResult:
        if self._pages_factory is None:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "Sauce Demo page factory is not configured.",
            )
        return process_account(item, self._pages_factory(context), context)

    def finalize(self, context: RunContext, result: RunResult) -> None:
        run_id = getattr(context, "run_id", result.run_id)
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
