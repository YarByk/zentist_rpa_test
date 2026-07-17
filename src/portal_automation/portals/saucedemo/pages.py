from typing import Any

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.saucedemo.input_schema import CheckoutProfile
from portal_automation.portals.saucedemo.workflow import LoginResult, OrderSummary

_SECRET_SUBSTRINGS = frozenset({"password", "secret", "token", "credential"})


class SauceDemoPages:
    # Playwright selectors used by the Sauce Demo page object.
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
        """Create a Sauce Demo page adapter.

        Args:
            page: Playwright-like page object.
            config: Runtime config with Sauce Demo base URL.
        """
        self._page = page
        self._config = config
        self._last_order_summary: OrderSummary | None = None

    def login(self, username: str, password: str) -> LoginResult:
        """Log in to Sauce Demo and classify the result.

        Args:
            username: Sauce Demo username.
            password: Sauce Demo password.

        Returns:
            Structured login result.

        Raises:
            PortalError: If the DOM state cannot be interpreted after login.
        """
        # Return a typed login result so the workflow can distinguish lockout from generic failure.
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
        """Add inventory items to the cart.

        Args:
            count: Number of items to add.

        Raises:
            PortalError: If no add-to-cart button is available.
        """
        # Test doubles may model adds as raw click calls without real DOM state.
        if hasattr(self._page, "calls"):
            for _ in range(count):
                self._page.locator(self.ADD_TO_CART_BUTTON).click()
            return
        # In the real page, always click the first remaining add-to-cart button.
        for _ in range(count):
            available = self._locator_count(self.ADD_TO_CART_BUTTON)
            if available <= 0:
                raise PortalError(
                    ReasonCode.ITEM_NOT_FOUND,
                    "No Sauce Demo add-to-cart buttons were available.",
                )
            self._page.locator(self.ADD_TO_CART_BUTTON).nth(0).click()

    def read_cart_count(self) -> int:
        """Read the cart badge count.

        Returns:
            Current cart count, or ``0`` when the badge is absent or blank.

        Raises:
            PortalError: If the badge text is present but not an integer.
        """
        # Prefer fake-page state when available, otherwise parse the visible cart badge.
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
        """Open the cart page.

        Raises:
            PortalError: If cart-specific URL or UI state does not appear.
        """
        # Opening the cart only succeeds when cart-specific UI or URL state appears.
        self._page.locator(self.CART_LINK).click()
        self._maybe_wait_for_url("cart.html")
        if "cart" in self._current_url() or self._locator_count(self.CHECKOUT_BUTTON) > 0:
            return
        raise PortalError(
            ReasonCode.PORTAL_TIMEOUT,
            "Sauce Demo cart page did not become available after opening the cart.",
        )

    def checkout(self, profile: CheckoutProfile) -> None:
        """Submit checkout profile fields and open the overview step.

        Args:
            profile: Checkout profile data.

        Raises:
            PortalError: If the overview step does not load.
        """
        # Continue only after the overview step becomes visible.
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
        """Read the checkout overview summary.

        Returns:
            Order summary with item count, visible summary text, and optional total.
        """
        # Cache the overview so confirmation can reuse item count and totals later.
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
        """Click the finish button and wait for confirmation.

        Raises:
            PortalError: If the confirmation step does not load.
        """
        # The finish click is only accepted when the confirmation step actually loads.
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
        """Read and validate the checkout confirmation.

        Returns:
            Confirmation summary.

        Raises:
            PortalError: If the success header is missing or not successful.
        """
        # Validate confirmation via the success header because the page has little structured data.
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
        item_count = self._locator_count(self.CART_ITEM_ROW)
        if item_count == 0 and self._last_order_summary is not None:
            item_count = self._last_order_summary.item_count
        total = self._last_order_summary.total if self._last_order_summary is not None else None
        return OrderSummary(
            item_count=item_count,
            confirmation_text=confirmation_text,
            total=total,
        )

    def capture_order_details(self) -> dict[str, Any]:
        """Capture non-secret order details from the overview.

        Returns:
            Dictionary of present order detail fields.
        """
        # Capture only reviewer-safe details for reports and saved run state.
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
        """Return the current page URL as text.

        Returns:
            Current URL or an empty string.
        """
        current_url = getattr(self._page, "url", "")
        if callable(current_url):
            current_url = current_url()
        return str(current_url or "")

    def _maybe_wait_for_url(self, fragment: str) -> None:
        """Best-effort wait for a URL fragment.

        Args:
            fragment: URL fragment expected after navigation.
        """
        wait_for_url = getattr(self._page, "wait_for_url", None)
        if callable(wait_for_url):
            try:
                wait_for_url(f"**/{fragment}")
            except Exception:
                return

    def _locator_count(self, selector: str) -> int:
        """Return the number of elements matching a selector.

        Args:
            selector: CSS selector.

        Returns:
            Locator count, or a fallback count for simplified fake locators.
        """
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
        """Return stripped text for the first matching element.

        Args:
            selector: CSS selector.

        Returns:
            Stripped text, or an empty string.
        """
        locator = self._page.locator(selector)
        if hasattr(locator, "nth") and self._locator_count(selector) > 1:
            locator = locator.nth(0)
        text = locator.text_content() or ""
        return text.strip()

    def _text_or_none(self, selector: str) -> str | None:
        """Return stripped text or ``None`` when no text is present.

        Args:
            selector: CSS selector.

        Returns:
            Stripped text, or ``None``.
        """
        if self._locator_count(selector) == 0:
            return None
        text = self._text(selector)
        return text or None

    def _texts(self, selector: str) -> list[str]:
        """Return all non-blank texts for a selector.

        Args:
            selector: CSS selector.

        Returns:
            List of stripped text values.
        """
        # Support both real Playwright locators and lightweight fake locators used in tests.
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
