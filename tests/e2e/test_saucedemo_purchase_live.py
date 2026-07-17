import os
from dataclasses import dataclass

import pytest

from portal_automation.core.browser import BrowserManager
from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.saucedemo.input_schema import CheckoutProfile
from portal_automation.portals.saucedemo.pages import SauceDemoPages
from portal_automation.portals.saucedemo.workflow import LoginStatus

pytestmark = pytest.mark.e2e


@dataclass
class ConfigStub:
    saucedemo_base_url: str = "https://www.saucedemo.com"
    headless: bool = True
    default_timeout_seconds: int = 30


def _require_live_run() -> None:
    """Require live run.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    if os.environ.get("RUN_LIVE_E2E") != "1":
        pytest.skip("Set RUN_LIVE_E2E=1 to run live SauceDemo purchase e2e tests.")


def test_saucedemo_live_standard_user_full_purchase() -> None:
    """Verify that saucedemo live standard user full purchase.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    _require_live_run()
    config = ConfigStub()
    try:
        with BrowserManager(config) as session:
            pages = SauceDemoPages(session.page, config)
            login_result = pages.login("standard_user", "secret_sauce")
            assert login_result.status is LoginStatus.SUCCESS

            pages.add_inventory_items(3)
            assert pages.read_cart_count() == 3
            pages.open_cart()
            pages.checkout(
                CheckoutProfile(
                    first_name="Standard",
                    last_name="User",
                    postal_code="10001",
                )
            )
            overview = pages.read_order_summary()
            details = pages.capture_order_details()
            assert overview.item_count == 3
            assert details["subtotal"]
            assert details["tax"]
            assert details["total"]
            assert len(details["item_names"]) == 3

            pages.finish_order()
            confirmation = pages.read_confirmation()
    except PortalError as exc:
        if exc.reason in {ReasonCode.PORTAL_UNAVAILABLE, ReasonCode.PORTAL_TIMEOUT}:
            pytest.skip(str(exc))
        raise

    assert "thank you for your order" in confirmation.confirmation_text.lower()
    assert confirmation.item_count == 3
