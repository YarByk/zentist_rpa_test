from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from portal_automation.core.models import ItemResult, ItemStatus, ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.saucedemo.input_schema import (
    CheckoutProfile,
    SauceDemoAccount,
)

OPERATION_NAME = "checkout"
SECRET_DETAIL_KEYS = frozenset({"password", "secret", "sauce_password", "token", "credential"})


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
) -> ItemResult:
    password = _saucedemo_password(context)
    login_result = pages.login(account.username, password)
    _raise_for_login_failure(account, login_result)

    pages.add_inventory_items(account.items_to_add)
    cart_count = pages.read_cart_count()
    if cart_count != account.items_to_add:
        raise PortalError(
            ReasonCode.VALIDATION_FAILED,
            (
                f"Cart count mismatch for '{account.account_key}': "
                f"expected {account.items_to_add}, got {cart_count}."
            ),
        )

    pages.open_cart()
    pages.checkout(account.checkout_profile)
    order_summary = pages.read_order_summary()
    if order_summary.item_count != account.items_to_add:
        raise PortalError(
            ReasonCode.VALIDATION_FAILED,
            (
                f"Order summary item count mismatch for '{account.account_key}': "
                f"expected {account.items_to_add}, got {order_summary.item_count}."
            ),
        )

    captured_raw = pages.capture_order_details()
    pages.finish_order()
    confirmation = pages.read_confirmation()
    _validate_confirmation(account, confirmation)
    details = _result_details(account, cart_count, confirmation, captured_raw)

    return ItemResult(
        item_key=account.account_key,
        operation=OPERATION_NAME,
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=None,
        attempts=1,
        details=details,
    )


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
