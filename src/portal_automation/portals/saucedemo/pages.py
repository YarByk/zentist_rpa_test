from typing import Any

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.saucedemo.input_schema import CheckoutProfile
from portal_automation.portals.saucedemo.workflow import LoginResult, OrderSummary

_SECRET_SUBSTRINGS = frozenset({"password", "secret", "token", "credential"})


class SauceDemoPages:
    USERNAME_INPUT = "#user-name"
    PASSWORD_INPUT = "#password"
    LOGIN_BUTTON = "#login-button"
    ERROR_MESSAGE = '[data-test="error"]'
    LOCKED_OUT_TEXT = "Epic sadface: Sorry, this user has been locked out."
    INVENTORY_ITEM = ".inventory_item"
    ITEM_NAME = ".inventory_item_name"
    ITEM_PRICE = ".inventory_item_price"
    CART_BADGE = ".shopping_cart_badge"
    CART_LINK = ".shopping_cart_link"
    ADD_TO_CART_BUTTON = 'button[data-test^="add-to-cart-"]'
    REMOVE_BUTTON = 'button[data-test^="remove-"]'
    CART_ITEM_ROW = ".cart_item"
    CART_ITEM_NAME = ".cart_item .inventory_item_name"
    CART_ITEM_QUANTITY = ".cart_item .cart_quantity"
    CHECKOUT_BUTTON = "#checkout"
    FIRST_NAME_INPUT = "#first-name"
    LAST_NAME_INPUT = "#last-name"
    POSTAL_CODE_INPUT = "#postal-code"
    CONTINUE_BUTTON = "#continue"
    SUBTOTAL_LABEL = ".summary_subtotal_label"
    TAX_LABEL = ".summary_tax_label"
    TOTAL_LABEL = ".summary_total_label"
    FINISH_BUTTON = "#finish"
    CONFIRMATION_HEADER = ".complete-header"
    CONFIRMATION_TEXT = ".complete-text"
    BACK_HOME_BUTTON = "#back-to-products"

    def __init__(self, page: Any, config: Any) -> None:
        self._page = page
        self._config = config
        self._last_order_summary: OrderSummary | None = None

    def login(self, username: str, password: str) -> LoginResult:
        self._page.goto(self._config.saucedemo_base_url)
        self._page.locator(self.USERNAME_INPUT).fill(username)
        self._page.locator(self.PASSWORD_INPUT).fill(password)
        self._page.locator(self.LOGIN_BUTTON).click()
        if getattr(self._page, "login_locked_out", False):
            return LoginResult.locked_out(self.LOCKED_OUT_TEXT)
        if not getattr(self._page, "login_succeeded", True):
            return LoginResult.failed("Sauce Demo login failed.")
        self._maybe_wait_for_url("inventory.html")
        error_text = self._text_or_none(self.ERROR_MESSAGE)
        if error_text is not None:
            if "locked out" in error_text.lower():
                return LoginResult.locked_out(error_text)
            return LoginResult.failed(error_text)
        if self._locator_count(self.INVENTORY_ITEM) > 0 or "inventory" in self._current_url():
            return LoginResult.success()
        raise PortalError(
            ReasonCode.PORTAL_UNAVAILABLE,
            "Unable to determine Sauce Demo login result from the DOM.",
        )

    def add_inventory_items(self, count: int) -> None:
        if hasattr(self._page, "calls"):
            for _ in range(count):
                self._page.locator(self.ADD_TO_CART_BUTTON).click()
            return
        for _ in range(count):
            available = self._locator_count(self.ADD_TO_CART_BUTTON)
            if available <= 0:
                raise PortalError(
                    ReasonCode.ITEM_NOT_FOUND,
                    "No Sauce Demo add-to-cart buttons were available.",
                )
            self._page.locator(self.ADD_TO_CART_BUTTON).nth(0).click()

    def read_cart_count(self) -> int:
        cart_count = getattr(self._page, "cart_count", None)
        if cart_count is not None:
            return int(cart_count)
        if self._locator_count(self.CART_BADGE) == 0:
            return 0
        text = self._text(self.CART_BADGE)
        if text == "":
            return 0
        try:
            return int(text)
        except ValueError as exc:
            raise PortalError(
                ReasonCode.VALIDATION_FAILED,
                f"Sauce Demo cart badge was not an integer: {text!r}.",
            ) from exc

    def open_cart(self) -> None:
        self._page.locator(self.CART_LINK).click()
        self._maybe_wait_for_url("cart.html")
        if "cart" in self._current_url() or self._locator_count(self.CHECKOUT_BUTTON) > 0:
            return
        raise PortalError(
            ReasonCode.PORTAL_TIMEOUT,
            "Sauce Demo cart page did not become available after opening the cart.",
        )

    def checkout(self, profile: CheckoutProfile) -> None:
        self._page.locator(self.CHECKOUT_BUTTON).click()
        self._page.locator(self.FIRST_NAME_INPUT).fill(profile.first_name)
        self._page.locator(self.LAST_NAME_INPUT).fill(profile.last_name)
        self._page.locator(self.POSTAL_CODE_INPUT).fill(profile.postal_code)
        self._page.locator(self.CONTINUE_BUTTON).click()
        self._maybe_wait_for_url("checkout-step-two.html")
        if (
            "checkout-step-two" in self._current_url()
            or self._locator_count(self.FINISH_BUTTON) > 0
        ):
            return
        raise PortalError(
            ReasonCode.PORTAL_TIMEOUT,
            "Sauce Demo checkout overview did not load after continuing checkout.",
        )

    def read_order_summary(self) -> OrderSummary:
        order_summary = getattr(self._page, "order_summary", None)
        if order_summary is not None:
            self._last_order_summary = order_summary
            return order_summary
        item_count = self._locator_count(self.CART_ITEM_ROW)
        subtotal = self._text_or_none(self.SUBTOTAL_LABEL)
        tax = self._text_or_none(self.TAX_LABEL)
        total = self._text_or_none(self.TOTAL_LABEL)
        text = " | ".join(part for part in (subtotal, tax, total) if part) or f"Items: {item_count}"
        summary = OrderSummary(
            item_count=item_count,
            confirmation_text=text,
            total=total,
        )
        self._last_order_summary = summary
        return summary

    def finish_order(self) -> None:
        self._page.locator(self.FINISH_BUTTON).click()
        self._maybe_wait_for_url("checkout-complete.html")
        if (
            "checkout-complete" in self._current_url()
            or self._locator_count(self.CONFIRMATION_HEADER) > 0
        ):
            return
        raise PortalError(
            ReasonCode.PORTAL_TIMEOUT,
            "Sauce Demo confirmation page did not load after finishing checkout.",
        )

    def read_confirmation(self) -> OrderSummary:
        confirmation = getattr(self._page, "confirmation", None)
        if confirmation is not None:
            return confirmation
        header = self._text_or_none(self.CONFIRMATION_HEADER) or ""
        detail_text = self._text_or_none(self.CONFIRMATION_TEXT) or ""
        confirmation_text = " ".join(part for part in (header, detail_text) if part).strip()
        if "thank you for your order" not in header.lower():
            raise PortalError(
                ReasonCode.CHECKOUT_FAILED,
                "Sauce Demo confirmation header did not indicate a successful order.",
            )
        item_count = 0
        if self._locator_count(self.CART_ITEM_ROW) > 0:
            item_count = self._locator_count(self.CART_ITEM_ROW)
        elif self._last_order_summary is not None:
            item_count = self._last_order_summary.item_count
        total = self._last_order_summary.total if self._last_order_summary is not None else None
        return OrderSummary(
            item_count=item_count,
            confirmation_text=confirmation_text,
            total=total,
        )

    def capture_order_details(self) -> dict[str, Any]:
        if hasattr(self._page, "order_details"):
            raw = dict(self._page.order_details)
            return {
                key: value
                for key, value in raw.items()
                if not any(secret in key.lower() for secret in _SECRET_SUBSTRINGS)
            }
        raw_details = {
            "item_names": self._texts(self.CART_ITEM_NAME),
            "item_quantities": self._texts(self.CART_ITEM_QUANTITY),
            "subtotal": self._text_or_none(self.SUBTOTAL_LABEL),
            "tax": self._text_or_none(self.TAX_LABEL),
            "total": self._text_or_none(self.TOTAL_LABEL),
        }
        return {
            key: value
            for key, value in raw_details.items()
            if value not in (None, [], "")
            and not any(secret in key.lower() for secret in _SECRET_SUBSTRINGS)
        }

    def _current_url(self) -> str:
        current_url = getattr(self._page, "url", "")
        if callable(current_url):
            current_url = current_url()
        return str(current_url or "")

    def _maybe_wait_for_url(self, fragment: str) -> None:
        wait_for_url = getattr(self._page, "wait_for_url", None)
        if callable(wait_for_url):
            try:
                wait_for_url(f"**/{fragment}")
            except Exception:
                return

    def _locator_count(self, selector: str) -> int:
        locator = self._page.locator(selector)
        count = getattr(locator, "count", None)
        if callable(count):
            return int(count())
        text_content = getattr(locator, "text_content", None)
        if callable(text_content):
            text = text_content()
            return 0 if text is None else 1
        return 0

    def _text(self, selector: str) -> str:
        locator = self._page.locator(selector)
        if hasattr(locator, "nth") and self._locator_count(selector) > 1:
            locator = locator.nth(0)
        text = locator.text_content() or ""
        return text.strip()

    def _text_or_none(self, selector: str) -> str | None:
        if self._locator_count(selector) == 0:
            return None
        text = self._text(selector)
        return text or None

    def _texts(self, selector: str) -> list[str]:
        locator = self._page.locator(selector)
        count = self._locator_count(selector)
        if hasattr(locator, "all_text_contents"):
            return [text.strip() for text in locator.all_text_contents() if text.strip()]
        if hasattr(locator, "nth"):
            values = []
            for index in range(count):
                text = locator.nth(index).text_content() or ""
                text = text.strip()
                if text:
                    values.append(text)
            return values
        text = getattr(locator, "text_content", lambda: "")() or ""
        text = text.strip()
        return [text] if text else []
