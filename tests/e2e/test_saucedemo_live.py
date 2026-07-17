import os
from dataclasses import dataclass

import pytest

from portal_automation.core.browser import BrowserManager
from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
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
        pytest.skip("Set RUN_LIVE_E2E=1 to run live SauceDemo e2e tests.")


@pytest.mark.parametrize(
    ("username", "expected_status"),
    [
        ("standard_user", LoginStatus.SUCCESS),
        ("locked_out_user", LoginStatus.LOCKED_OUT),
        ("problem_user", LoginStatus.SUCCESS),
        ("performance_glitch_user", LoginStatus.SUCCESS),
        ("error_user", LoginStatus.SUCCESS),
        ("visual_user", LoginStatus.SUCCESS),
    ],
)
def test_saucedemo_live_login_all_demo_accounts(
    username: str,
    expected_status: LoginStatus,
) -> None:
    """Verify that saucedemo live login all demo accounts.
    
    Args:
        username: Value supplied by the test or fixture for `username`.
        expected_status: Value supplied by the test or fixture for `expected_status`.
    
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
            result = pages.login(username, "secret_sauce")
    except PortalError as exc:
        if exc.reason in {ReasonCode.PORTAL_UNAVAILABLE, ReasonCode.PORTAL_TIMEOUT}:
            pytest.skip(str(exc))
        raise

    assert result.status is expected_status
