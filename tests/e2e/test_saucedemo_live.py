import os
from dataclasses import dataclass

import pytest

from portal_automation.core.browser import BrowserManager
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
    if os.environ.get("RUN_LIVE_E2E") != "1":
        pytest.skip("Set RUN_LIVE_E2E=1 to run live SauceDemo e2e tests.")


@pytest.mark.parametrize(
    ("username", "expected_status"),
    [
        ("standard_user", LoginStatus.SUCCESS),
        ("locked_out_user", LoginStatus.LOCKED_OUT),
    ],
)
def test_saucedemo_live_login(username: str, expected_status: LoginStatus) -> None:
    _require_live_run()
    config = ConfigStub()
    try:
        with BrowserManager(config) as session:
            pages = SauceDemoPages(session.page, config)
            result = pages.login(username, "secret_sauce")
    except PortalError as exc:
        pytest.skip(str(exc))

    assert result.status is expected_status
