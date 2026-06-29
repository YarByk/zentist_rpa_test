from collections.abc import Callable
from typing import Any

from portal_automation.core.models import ItemResult, ReasonCode, RunContext, RunResult
from portal_automation.core.retries import PortalError
from portal_automation.core.runner import BasePortalRunnerZX
from portal_automation.portals.orangehrm.input_schema import (
    InputValidationError,
    load_employee_records,
)
from portal_automation.portals.orangehrm.workflow import (
    OrangeHrmWorkflowPages,
    process_employee,
)


class OrangeHrmRunner(BasePortalRunnerZX):
    portal_name = "orangehrm"
    operation_name = "sync_employee_state"
    max_sessions_per_login = 1

    def __init__(
        self,
        pages_factory: Callable[[RunContext], OrangeHrmWorkflowPages] | None = None,
    ) -> None:
        self._pages_factory = pages_factory

    def preflight_check(self, context: RunContext) -> None:
        password = getattr(context.config, "orangehrm_password", None)
        if not isinstance(password, str) or not password.strip():
            raise PortalError(
                ReasonCode.CREDENTIAL_EXPIRED,
                "OrangeHRM password is not configured.",
            )

    def load_items(self, context: RunContext) -> list[Any]:
        try:
            return load_employee_records(context.config.orangehrm_input_path)
        except InputValidationError as exc:
            raise PortalError(ReasonCode.INPUT_VALIDATION_FAILED, str(exc)) from exc

    def item_key(self, item: Any) -> str:
        if hasattr(item, "employee_key"):
            return str(item.employee_key)
        return super().item_key(item)

    def process_item(self, context: RunContext, item: Any) -> ItemResult:
        if self._pages_factory is None:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "OrangeHRM page factory is not configured.",
            )
        return process_employee(item, self._pages_factory(context), context)

    def finalize(self, context: RunContext, result: RunResult) -> None:
        if hasattr(context.reporter, "write_report"):
            context.reporter.write_report(result)
