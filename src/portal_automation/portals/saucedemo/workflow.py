from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from portal_automation.core.models import ItemResult, ItemStatus, ReasonCode
from portal_automation.core.retries import (
    PortalError,
    execute_with_context_retry,
    is_retryable_error,
)
from portal_automation.portals.saucedemo.input_schema import (
    CheckoutProfile,
    SauceDemoAccount,
)

OPERATION_NAME = "checkout"
SECRET_DETAIL_KEYS = frozenset({"password", "secret", "sauce_password", "token", "credential"})
PreFinishPersistCallback = Callable[[ItemResult], None]


class LoginStatus(str, Enum):  # noqa: UP042
    SUCCESS = "success"
    LOCKED_OUT = "locked_out"
    FAILED = "failed"


@dataclass(frozen=True)
class LoginResult:
    status: LoginStatus
    detail: str = ""

    @classmethod
    def success(cls) -> "LoginResult":
        """Return a successful login result.

        Returns:
            ``LoginResult`` with status ``SUCCESS``.
        """
        return cls(LoginStatus.SUCCESS)

    @classmethod
    def locked_out(cls, detail: str = "") -> "LoginResult":
        """Return a locked-out login result.

        Args:
            detail: Optional human-readable lockout detail.

        Returns:
            ``LoginResult`` with status ``LOCKED_OUT``.
        """
        return cls(LoginStatus.LOCKED_OUT, detail)

    @classmethod
    def failed(cls, detail: str = "") -> "LoginResult":
        """Return a failed login result.

        Args:
            detail: Optional human-readable failure detail.

        Returns:
            ``LoginResult`` with status ``FAILED``.
        """
        return cls(LoginStatus.FAILED, detail)


@dataclass(frozen=True)
class OrderSummary:
    item_count: int
    confirmation_text: str
    order_id: str | None = None
    total: str | None = None


class SauceDemoWorkflowPages(Protocol):
    def login(self, username: str, password: str) -> LoginResult:
        """Authenticate a Sauce Demo account.

        Args:
            username: Account username.
            password: Runtime password.

        Returns:
            Structured login result.

        Raises:
            PortalError: If the portal interaction fails before a result can be returned.
        """
        return LoginResult.failed("workflow interface method was called directly")

    def add_inventory_items(self, count: int) -> None:
        """Add inventory items to the cart.

        Args:
            count: Number of additional items to add.

        Raises:
            PortalError: If items cannot be added.
        """
        return

    def read_cart_count(self) -> int:
        """Read the visible cart item count.

        Returns:
            Current cart item count.

        Raises:
            PortalError: If the cart count cannot be read or parsed.
        """
        return 0

    def open_cart(self) -> None:
        """Open the cart view.

        Raises:
            PortalError: If the cart view cannot be opened.
        """
        return

    def checkout(self, profile: CheckoutProfile) -> None:
        """Submit checkout profile information and open the overview.

        Args:
            profile: Checkout profile from input data.

        Raises:
            PortalError: If checkout cannot advance to the overview step.
        """
        return

    def read_order_summary(self) -> OrderSummary:
        """Read the checkout overview summary.

        Returns:
            Order summary from the overview step.

        Raises:
            PortalError: If the summary cannot be read.
        """
        return OrderSummary(item_count=0, confirmation_text="")

    def finish_order(self) -> None:
        """Finish the order from the checkout overview.

        Raises:
            PortalError: If the finish action fails.
        """
        return

    def read_confirmation(self) -> OrderSummary:
        """Read the completed checkout confirmation.

        Returns:
            Confirmation summary.

        Raises:
            PortalError: If confirmation cannot be read or validated.
        """
        return OrderSummary(item_count=0, confirmation_text="")

    def capture_order_details(self) -> dict[str, Any]:
        """Capture optional order details before the final finish action.

        Returns:
            Dictionary of order details safe for workflow processing.

        Raises:
            PortalError: If order details cannot be captured.
        """
        return {}


def process_account(
    account: SauceDemoAccount,
    pages: SauceDemoWorkflowPages,
    context: Any,
    *,
    persist_before_finish: PreFinishPersistCallback | None = None,
) -> ItemResult:
    """Complete one Sauce Demo checkout account workflow.

    Args:
        account: Account input record.
        pages: Workflow page adapter.
        context: Runtime context with config and retry settings.
        persist_before_finish: Optional callback used to persist order details before finishing.

    Returns:
        Successful checkout item result.

    Raises:
        PortalError: If login, cart setup, checkout, summary validation, finish, or confirmation
            validation fails.
        Exception: If ``persist_before_finish`` raises.
    """
    password = _saucedemo_password(context)
    attempts = 1
    # Each account is processed independently so one locked-out demo user does not stop the batch.

    login_result, login_attempts = execute_with_context_retry(
        context,
        lambda: pages.login(account.username, password),
    )
    attempts = max(attempts, login_attempts)
    _raise_for_login_failure(account, login_result)

    cart_count, cart_attempts = _ensure_cart_count(account, pages, context)
    attempts = max(attempts, cart_attempts)

    _, open_cart_attempts = execute_with_context_retry(context, pages.open_cart)
    attempts = max(attempts, open_cart_attempts)

    order_summary, summary_attempts = _checkout_and_read_summary(account, pages, context)
    attempts = max(attempts, summary_attempts)
    if order_summary.item_count != account.items_to_add:
        raise PortalError(
            ReasonCode.VALIDATION_FAILED,
            (
                f"Order summary item count mismatch for '{account.account_key}': "
                f"expected {account.items_to_add}, got {order_summary.item_count}."
            ),
        )

    captured_raw, capture_attempts = execute_with_context_retry(
        context,
        pages.capture_order_details,
    )
    attempts = max(attempts, capture_attempts)

    # Persist order details before finishing so recovery can inspect progress after partial failure.
    _persist_order_details_before_finish(
        persist_before_finish,
        _pre_finish_result(account, cart_count, order_summary, captured_raw, attempts),
    )

    confirmation, confirmation_attempts = _finish_order_and_read_confirmation(
        account,
        pages,
        context,
    )
    attempts = max(attempts, confirmation_attempts)
    _validate_confirmation(account, confirmation)
    details = _result_details(account, cart_count, confirmation, captured_raw)

    return ItemResult(
        item_key=account.account_key,
        operation=OPERATION_NAME,
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
        attempts=attempts,
        details=details,
    )


def _persist_order_details_before_finish(
    persist_before_finish: PreFinishPersistCallback | None,
    result: ItemResult,
) -> None:
    """Run the optional pre-finish save callback.

    Args:
        persist_before_finish: Callback supplied by the runner, or ``None``.
        result: In-progress result carrying captured order details.

    Raises:
        Exception: Any exception raised by ``persist_before_finish`` is propagated.
    """
    if persist_before_finish is None:
        return
    persist_before_finish(result)


def _pre_finish_result(
    account: SauceDemoAccount,
    cart_count: int,
    order_summary: OrderSummary,
    captured_details: dict[str, Any],
    attempts: int,
) -> ItemResult:
    """Build the in-progress result persisted before finishing checkout.

    Args:
        account: Account input record.
        cart_count: Current cart count.
        order_summary: Checkout overview summary.
        captured_details: Additional details captured from the overview.
        attempts: Max attempts used so far.

    Returns:
        In-progress item result containing pre-finish details.
    """
    return ItemResult(
        item_key=account.account_key,
        operation=OPERATION_NAME,
        status=ItemStatus.IN_PROGRESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
        attempts=attempts,
        details=_pre_finish_details(account, cart_count, order_summary, captured_details),
    )


def _pre_finish_details(
    account: SauceDemoAccount,
    cart_count: int,
    order_summary: OrderSummary,
    captured_details: dict[str, Any],
) -> dict[str, Any]:
    """Build sanitized pre-finish detail payload.

    Args:
        account: Account input record.
        cart_count: Current cart count.
        order_summary: Checkout overview summary.
        captured_details: Additional details captured from the overview.

    Returns:
        Dictionary safe to persist before checkout is finished.
    """
    details: dict[str, Any] = {
        "username": account.username,
        "items_requested": account.items_to_add,
        "cart_count": cart_count,
        "overview_item_count": order_summary.item_count,
        "overview_text": order_summary.confirmation_text.strip(),
        "order_details_captured_before_finish": True,
    }
    if order_summary.order_id is not None:
        details["overview_order_id"] = order_summary.order_id
    if order_summary.total is not None:
        details["overview_total"] = order_summary.total
    details.update(_non_secret_details(captured_details))
    return details


def _ensure_cart_count(
    account: SauceDemoAccount,
    pages: SauceDemoWorkflowPages,
    context: Any,
) -> tuple[int, int]:
    """Ensure the cart contains the requested item count.

    Args:
        account: Account input record.
        pages: Workflow page adapter.
        context: Runtime context used for retries.

    Returns:
        Tuple of final cart count and max attempts used.

    Raises:
        PortalError: If the cart is overfilled, item adding fails, or final count is wrong.
    """
    attempts = 1
    max_attempts = getattr(context.config, "max_retries", 0) + 1
    # Read the cart first so pre-populated state can be reused instead of duplicated.
    current_count, read_attempts = execute_with_context_retry(context, pages.read_cart_count)
    attempts = max(attempts, read_attempts)
    _raise_for_cart_overage(account, current_count)
    remaining = account.items_to_add - current_count
    if remaining == 0:
        return current_count, attempts

    last_retryable_error: PortalError | None = None
    for add_attempt in range(1, max_attempts + 1):
        try:
            pages.add_inventory_items(remaining)
            last_retryable_error = None
        except PortalError as error:
            if not is_retryable_error(error):
                raise
            last_retryable_error = error
            attempts = max(attempts, error.attempts, add_attempt)

        # Re-read after every add attempt because the portal may have applied a partial change.
        current_count, verify_attempts = execute_with_context_retry(context, pages.read_cart_count)
        attempts = max(attempts, verify_attempts)
        _raise_for_cart_overage(account, current_count)
        remaining = account.items_to_add - current_count
        if remaining == 0:
            return current_count, attempts
        if last_retryable_error is not None and add_attempt >= max_attempts:
            last_retryable_error.attempts = attempts
            raise last_retryable_error

    raise PortalError(
        ReasonCode.VALIDATION_FAILED,
        (
            f"Cart count mismatch for '{account.account_key}': "
            f"expected {account.items_to_add}, got {current_count}."
        ),
        attempts=attempts,
    )


def _raise_for_cart_overage(account: SauceDemoAccount, current_count: int) -> None:
    """Fail when the cart already contains more items than requested.

    Args:
        account: Account input record.
        current_count: Current cart count.

    Raises:
        PortalError: If ``current_count`` exceeds ``account.items_to_add``.
    """
    if current_count > account.items_to_add:
        raise PortalError(
            ReasonCode.VALIDATION_FAILED,
            (
                f"Cart count mismatch for '{account.account_key}': "
                f"expected {account.items_to_add}, got {current_count}."
            ),
        )


def _checkout_and_read_summary(
    account: SauceDemoAccount,
    pages: SauceDemoWorkflowPages,
    context: Any,
) -> tuple[OrderSummary, int]:
    """Submit checkout information and read the overview summary.

    Args:
        account: Account input record.
        pages: Workflow page adapter.
        context: Runtime context used for retries.

    Returns:
        Tuple of overview summary and max attempts used.

    Raises:
        PortalError: If checkout or summary reading fails.
    """
    attempts = 1
    try:
        pages.checkout(account.checkout_profile)
    except PortalError as error:
        if not is_retryable_error(error):
            raise
        attempts = max(attempts, error.attempts)
        summary, read_attempts = execute_with_context_retry(context, pages.read_order_summary)
        attempts = max(attempts, read_attempts)
        if summary.item_count == account.items_to_add and summary.confirmation_text.strip():
            return summary, attempts
        error.attempts = attempts
        raise

    summary, read_attempts = execute_with_context_retry(context, pages.read_order_summary)
    attempts = max(attempts, read_attempts)
    return summary, attempts


def _finish_order_and_read_confirmation(
    account: SauceDemoAccount,
    pages: SauceDemoWorkflowPages,
    context: Any,
) -> tuple[OrderSummary, int]:
    """Finish checkout and read confirmation.

    Args:
        account: Account input record.
        pages: Workflow page adapter.
        context: Runtime context used for retries.

    Returns:
        Tuple of confirmation summary and max attempts used.

    Raises:
        PortalError: If finishing or confirmation validation fails.
    """
    attempts = 1
    try:
        pages.finish_order()
    except PortalError as error:
        if not is_retryable_error(error):
            raise
        attempts = max(attempts, error.attempts)
        confirmation, read_attempts = execute_with_context_retry(context, pages.read_confirmation)
        attempts = max(attempts, read_attempts)
        try:
            _validate_confirmation(account, confirmation)
        except PortalError:
            error.attempts = attempts
            raise error from None
        return confirmation, attempts

    confirmation, read_attempts = execute_with_context_retry(context, pages.read_confirmation)
    attempts = max(attempts, read_attempts)
    return confirmation, attempts


def _saucedemo_password(context: Any) -> str:
    """Read the configured Sauce Demo password from context.

    Args:
        context: Runtime context with ``config.saucedemo_password``.

    Returns:
        Trimmed password.

    Raises:
        PortalError: If the password is missing or blank.
    """
    config = getattr(context, "config", None)
    password = getattr(config, "saucedemo_password", None)
    if not isinstance(password, str) or not password.strip():
        raise PortalError(
            ReasonCode.CREDENTIAL_EXPIRED,
            "Sauce Demo password is not configured.",
        )
    return password.strip()


def _raise_for_login_failure(account: SauceDemoAccount, login_result: LoginResult) -> None:
    """Map a non-success login result to a portal-domain error.

    Args:
        account: Account input record.
        login_result: Login result returned by the page adapter.

    Raises:
        PortalError: If login was locked out or failed.
    """
    if login_result.status is LoginStatus.SUCCESS:
        return
    if login_result.status is LoginStatus.LOCKED_OUT:
        detail = login_result.detail or f"Sauce Demo account '{account.account_key}' is locked out."
        raise PortalError(ReasonCode.LOCKED_OUT, detail)

    detail = login_result.detail or f"Sauce Demo login failed for '{account.account_key}'."
    raise PortalError(ReasonCode.LOGIN_FAILED, detail)


def _validate_confirmation(account: SauceDemoAccount, confirmation: OrderSummary) -> None:
    """Validate checkout confirmation content.

    Args:
        account: Account input record.
        confirmation: Confirmation summary.

    Raises:
        PortalError: If confirmation text is blank or item count is wrong.
    """
    if not confirmation.confirmation_text.strip():
        raise PortalError(
            ReasonCode.CHECKOUT_FAILED,
            f"Sauce Demo confirmation was blank for '{account.account_key}'.",
        )
    if confirmation.item_count != account.items_to_add:
        raise PortalError(
            ReasonCode.CHECKOUT_FAILED,
            (
                f"Sauce Demo confirmation item count mismatch for '{account.account_key}': "
                f"expected {account.items_to_add}, got {confirmation.item_count}."
            ),
        )


def _result_details(
    account: SauceDemoAccount,
    cart_count: int,
    confirmation: OrderSummary,
    captured_details: dict[str, Any],
) -> dict[str, Any]:
    """Build the final successful result details payload.

    Args:
        account: Account input record.
        cart_count: Final cart count.
        confirmation: Confirmation summary.
        captured_details: Additional captured order details.

    Returns:
        Dictionary safe to store on the final item result.
    """
    details: dict[str, Any] = {
        "username": account.username,
        "items_requested": account.items_to_add,
        "cart_count": cart_count,
        "confirmation_text": confirmation.confirmation_text.strip(),
    }
    if confirmation.order_id is not None:
        details["order_id"] = confirmation.order_id
    if confirmation.total is not None:
        details["total"] = confirmation.total
    details.update(_non_secret_details(captured_details))
    return details


def _non_secret_details(captured_details: dict[str, Any]) -> dict[str, Any]:
    """Filter captured details by removing credential-like keys.

    Args:
        captured_details: Raw detail dictionary captured from the page adapter.

    Returns:
        Detail dictionary without secret-like keys.
    """
    # Filter dynamic page captures defensively so artifacts never store credential-like fields.
    return {
        key: value
        for key, value in captured_details.items()
        if not any(secret_key in key.lower() for secret_key in SECRET_DETAIL_KEYS)
    }
