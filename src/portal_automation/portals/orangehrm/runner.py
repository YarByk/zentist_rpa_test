from collections.abc import Callable
from typing import Any

from portal_automation.core.models import ItemResult, ReasonCode, RunContext, RunResult
from portal_automation.core.retries import PortalError, execute_with_context_retry
from portal_automation.core.runner import BasePortalRunnerZX
from portal_automation.portals.orangehrm.input_schema import (
    InputValidationError,
    load_employee_records,
)
from portal_automation.portals.orangehrm.workflow import (
    OrangeHrmWorkflowPages,
    process_employee,
)


class _ReloginOnSessionDropPages:
    """Page adapter wrapper that refreshes OrangeHRM login after an in-flow logout.

    The workflow already contains idempotent recovery points around create/update/upload actions.
    This wrapper keeps that logic intact: when a page method detects ``SESSION_DROPPED``, the
    wrapper performs a fresh login and re-raises the same error so the workflow retry/recovery
    branch can repeat the safest next step.
    """

    def __init__(
        self,
        pages: OrangeHrmWorkflowPages,
        relogin: Callable[[], OrangeHrmWorkflowPages],
    ) -> None:
        """Create a relogin-aware page proxy.

        Args:
            pages: Underlying OrangeHRM page adapter.
            relogin: Callback that restores an authenticated OrangeHRM session.
        """
        self._pages = pages
        self._relogin = relogin

    def __getattr__(self, name: str) -> Any:
        """Return an attribute from the wrapped page adapter.

        Args:
            name: Attribute name requested by the workflow.

        Returns:
            Original attribute, or a wrapped callable for page actions.
        """
        target = getattr(self._pages, name)
        if not callable(target):
            return target

        def call_with_session_recovery(*args: Any, **kwargs: Any) -> Any:
            """Run one page action and refresh login when OrangeHRM expires the session."""
            try:
                return target(*args, **kwargs)
            except PortalError as error:
                if error.reason is ReasonCode.SESSION_DROPPED:
                    self._pages = self._relogin()
                raise

        return call_with_session_recovery


class OrangeHrmRunner(BasePortalRunnerZX):
    portal_name = "orangehrm"
    operation_name = "sync_employee_state"

    def __init__(
        self,
        pages_factory: Callable[[RunContext], OrangeHrmWorkflowPages] | None = None,
    ) -> None:
        """Create an OrangeHRM runner.

        Args:
            pages_factory: Optional factory that creates the workflow page adapter for live runs.
        """
        self._pages_factory = pages_factory
        self._pages: OrangeHrmWorkflowPages | None = None
        self._logged_in = False
        self._login_error: PortalError | None = None
        self._has_successful_login = False
        self._stop_after_initial_login_unavailable = False

    def preflight_check(self, context: RunContext) -> None:
        """Validate OrangeHRM live-run prerequisites.

        Args:
            context: Runtime context.

        Raises:
            PortalError: If the OrangeHRM password is missing or blank.
        """
        password = getattr(context.config, "orangehrm_password", None)
        if not isinstance(password, str) or not password.strip():
            raise PortalError(
                ReasonCode.CREDENTIAL_EXPIRED,
                "OrangeHRM password is not configured.",
            )

    def load_items(self, context: RunContext) -> list[Any]:
        """Load OrangeHRM employee input records.

        Args:
            context: Runtime context with ``config.orangehrm_input_path``.

        Returns:
            Validated employee records.

        Raises:
            PortalError: If input validation fails.
        """
        try:
            return load_employee_records(context.config.orangehrm_input_path)
        except InputValidationError as exc:
            raise PortalError(ReasonCode.INPUT_VALIDATION_FAILED, str(exc)) from exc

    def item_key(self, item: Any) -> str:
        """Return the employee key for an OrangeHRM input item.

        Args:
            item: Employee record or fallback item.

        Returns:
            Employee key string.
        """
        if hasattr(item, "employee_key"):
            return str(item.employee_key)
        return super().item_key(item)

    def process_item(self, context: RunContext, item: Any) -> ItemResult:
        """Process one employee through the OrangeHRM workflow.

        Args:
            context: Runtime context.
            item: Employee record to process.

        Returns:
            Item result from ``process_employee``.

        Raises:
            PortalError: If login or employee processing fails with a portal-domain reason.
        """
        # OrangeHRM reuses a single authenticated session across all employees in the run.
        pages = self._ensure_logged_in(context)
        guarded_pages = _ReloginOnSessionDropPages(
            pages,
            lambda: self._relogin_after_session_drop(context),
        )
        return process_employee(item, guarded_pages, context)

    def _ensure_logged_in(self, context: RunContext) -> OrangeHrmWorkflowPages:
        """Create page adapter if needed and ensure the session is logged in.

        Args:
            context: Runtime context.

        Returns:
            Logged-in workflow page adapter.

        Raises:
            PortalError: If the page factory is missing, login support is missing, or login fails.
        """
        if self._login_error is not None:
            raise self._login_error
        if self._pages is None:
            if self._pages_factory is None:
                raise PortalError(
                    ReasonCode.PORTAL_UNAVAILABLE,
                    "OrangeHRM page factory is not configured.",
                )
            self._pages = self._pages_factory(context)
        if self._logged_in:
            is_authenticated = getattr(self._pages, "is_authenticated", None)
            if callable(is_authenticated) and not is_authenticated():
                # The browser may have been redirected back to login during a long public-demo run.
                # In that case we keep the same page object but perform a fresh login.
                self._logged_in = False
            else:
                return self._pages

        username = getattr(context.config, "orangehrm_username", "")
        password = getattr(context.config, "orangehrm_password", None)
        login = getattr(self._pages, "login", None)
        if not callable(login):
            self._login_error = PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "OrangeHRM pages do not support login.",
            )
            raise self._login_error

        try:
            execute_with_context_retry(context, lambda: login(username, password))
        except PortalError as error:
            if error.reason is ReasonCode.PORTAL_UNAVAILABLE and not self._has_successful_login:
                self._login_error = error
                self._stop_after_initial_login_unavailable = True
            elif error.reason is not ReasonCode.PORTAL_TIMEOUT and not self._has_successful_login:
                self._login_error = error
            raise
        # Cache the successful login so later employees do not repeat portal authentication.
        self._logged_in = True
        self._has_successful_login = True
        return self._pages

    def _relogin_after_session_drop(self, context: RunContext) -> OrangeHrmWorkflowPages:
        """Log in again after OrangeHRM redirects an active run back to the login page.

        Args:
            context: Runtime context with credentials and retry settings.

        Returns:
            Re-authenticated workflow page adapter.

        Raises:
            PortalError: If the replacement login attempt fails.
        """
        self._logged_in = False
        return self._ensure_logged_in(context)

    def _should_stop_item_iteration(self, context: RunContext, result: ItemResult) -> bool:
        """Stop the run after a startup-only OrangeHRM login-page outage.

        Args:
            context: Runtime context.
            result: Most recently persisted item result.

        Returns:
            ``True`` only when the run never reached a successful OrangeHRM session and the first
            login attempt sequence proved the login page unavailable.
        """
        return (
            self._stop_after_initial_login_unavailable
            and not self._has_successful_login
            and result.reason_code is ReasonCode.PORTAL_UNAVAILABLE
        )

    def finalize(self, context: RunContext, result: RunResult) -> None:
        """Write report artifacts and send the OrangeHRM run notification.

        Args:
            context: Runtime context.
            result: Final run result.

        Raises:
            Exception: If report writing or email delivery fails.
        """
        run_id = getattr(context, "run_id", result.run_id)
        report_path = None
        if hasattr(context.reporter, "write_report"):
            report_path = context.reporter.write_report(result)
        email = getattr(context, "email", None)
        if hasattr(email, "send_report"):
            body = (
                context.reporter.render(result)
                if hasattr(context.reporter, "render")
                else f"Portal run {result.run_id} completed with status {result.status.value}."
            )
            email.send_report(
                run_id=run_id,
                to=getattr(context.config, "report_email_to", None),
                subject=f"OrangeHRM run report: {run_id}",
                body=body,
                report_path=report_path,
            )
