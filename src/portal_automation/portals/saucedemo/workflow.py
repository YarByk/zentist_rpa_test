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
        return cls(LoginStatus.SUCCESS)

    @classmethod
    def locked_out(cls, detail: str = "") -> "LoginResult":
        return cls(LoginStatus.LOCKED_OUT, detail)

    @classmethod
    def failed(cls, detail: str = "") -> "LoginResult":
        return cls(LoginStatus.FAILED, detail)


@dataclass(frozen=True)
class OrderSummary:
    item_count: int
    confirmation_text: str
    order_id: str | None = None
    total: str | None = None


class SauceDemoWorkflowPages(Protocol):
    def login(self, username: str, password: str) -> LoginResult:
        return LoginResult.failed("workflow interface method was called directly")

    def add_inventory_items(self, count: int) -> None:
        return

    def read_cart_count(self) -> int:
        return 0

    def open_cart(self) -> None:
        return

    def checkout(self, profile: CheckoutProfile) -> None:
        return

    def read_order_summary(self) -> OrderSummary:
        return OrderSummary(item_count=0, confirmation_text="")

    def finish_order(self) -> None:
        return

    def read_confirmation(self) -> OrderSummary:
        return OrderSummary(item_count=0, confirmation_text="")

    def capture_order_details(self) -> dict[str, Any]:
        return {}


def process_account(
    account: SauceDemoAccount,
    pages: SauceDemoWorkflowPages,
    context: Any,
    *,
    persist_before_finish: PreFinishPersistCallback | None = None,
) -> ItemResult:
    password = _saucedemo_password(context)
    attempts = 1

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
    attempts = 1
    max_attempts = getattr(context.config, "max_retries", 0) + 1
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
    config = getattr(context, "config", None)
    password = getattr(config, "saucedemo_password", None)
    if not isinstance(password, str) or not password.strip():
        raise PortalError(
            ReasonCode.CREDENTIAL_EXPIRED,
            "Sauce Demo password is not configured.",
        )
    return password.strip()


def _raise_for_login_failure(account: SauceDemoAccount, login_result: LoginResult) -> None:
    if login_result.status is LoginStatus.SUCCESS:
        return
    if login_result.status is LoginStatus.LOCKED_OUT:
        detail = login_result.detail or f"Sauce Demo account '{account.account_key}' is locked out."
        raise PortalError(ReasonCode.LOCKED_OUT, detail)

    detail = login_result.detail or f"Sauce Demo login failed for '{account.account_key}'."
    raise PortalError(ReasonCode.LOGIN_FAILED, detail)


def _validate_confirmation(account: SauceDemoAccount, confirmation: OrderSummary) -> None:
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
    return {
        key: value
        for key, value in captured_details.items()
        if not any(secret_key in key.lower() for secret_key in SECRET_DETAIL_KEYS)
    }
