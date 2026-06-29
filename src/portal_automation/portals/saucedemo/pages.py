from typing import Any

from portal_automation.portals.saucedemo.input_schema import CheckoutProfile
from portal_automation.portals.saucedemo.workflow import LoginResult, OrderSummary

_SECRET_SUBSTRINGS = frozenset({"password", "secret", "token", "credential"})


class SauceDemoPages:
    USERNAME_INPUT = "#user-name"
    PASSWORD_INPUT = "#password"
    LOGIN_BUTTON = "#login-button"
    LOCKED_OUT_TEXT = "Epic sadface: Sorry, this user has been locked out."
    CART_BADGE = ".shopping_cart_badge"
    CART_LINK = ".shopping_cart_link"
    ADD_TO_CART_BUTTON = "[data-test^='add-to-cart']"
    CHECKOUT_BUTTON = "#checkout"
    FIRST_NAME_INPUT = "#first-name"
    LAST_NAME_INPUT = "#last-name"
    POSTAL_CODE_INPUT = "#postal-code"
    CONTINUE_BUTTON = "#continue"
    SUMMARY_HEADER = ".subheader"
    FINISH_BUTTON = "#finish"
    CONFIRMATION_HEADER = ".complete-header"

    def __init__(self, page: Any, config: Any) -> None:
        self._page = page
        self._config = config

    def login(self, username: str, password: str) -> LoginResult:
        self._page.goto(self._config.saucedemo_base_url)
        self._page.locator(self.USERNAME_INPUT).fill(username)
        self._page.locator(self.PASSWORD_INPUT).fill(password)
        self._page.locator(self.LOGIN_BUTTON).click()
        if getattr(self._page, "login_locked_out", False):
            return LoginResult.locked_out(self.LOCKED_OUT_TEXT)
        if not getattr(self._page, "login_succeeded", True):
            return LoginResult.failed("Sauce Demo login failed.")
        return LoginResult.success()

    def add_inventory_items(self, count: int) -> None:
        for _ in range(count):
            add_button = self._page.locator(self.ADD_TO_CART_BUTTON)
            if hasattr(add_button, "first"):
                add_button = add_button.first()
            add_button.click()

    def read_cart_count(self) -> int:
        cart_count = getattr(self._page, "cart_count", None)
        if cart_count is not None:
            return int(cart_count)
        text = (self._page.locator(self.CART_BADGE).text_content() or "").strip()
        return int(text) if text.isdigit() else 0

    def open_cart(self) -> None:
        self._page.locator(self.CART_LINK).click()

    def checkout(self, profile: CheckoutProfile) -> None:
        self._page.locator(self.CHECKOUT_BUTTON).click()
        self._page.locator(self.FIRST_NAME_INPUT).fill(profile.first_name)
        self._page.locator(self.LAST_NAME_INPUT).fill(profile.last_name)
        self._page.locator(self.POSTAL_CODE_INPUT).fill(profile.postal_code)
        self._page.locator(self.CONTINUE_BUTTON).click()

    def read_order_summary(self) -> OrderSummary:
        order_summary = getattr(self._page, "order_summary", None)
        if order_summary is not None:
            return order_summary
        text = (self._page.locator(self.SUMMARY_HEADER).text_content() or "").strip()
        item_count = getattr(self._page, "summary_item_count", 0)
        return OrderSummary(item_count=item_count, confirmation_text=text)

    def finish_order(self) -> None:
        self._page.locator(self.FINISH_BUTTON).click()

    def read_confirmation(self) -> OrderSummary:
        confirmation = getattr(self._page, "confirmation", None)
        if confirmation is not None:
            return confirmation
        text = (self._page.locator(self.CONFIRMATION_HEADER).text_content() or "").strip()
        item_count = getattr(self._page, "confirmation_item_count", 0)
        return OrderSummary(item_count=item_count, confirmation_text=text)

    def capture_order_details(self) -> dict[str, Any]:
        if hasattr(self._page, "order_details"):
            raw = dict(self._page.order_details)
            return {
                key: value
                for key, value in raw.items()
                if not any(secret in key.lower() for secret in _SECRET_SUBSTRINGS)
            }
        return {}
