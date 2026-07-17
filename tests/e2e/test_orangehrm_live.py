"""Opt-in live e2e tests for OrangeHRM portal.

Run only when RUN_LIVE_E2E=1 is set:
    RUN_LIVE_E2E=1 pytest -m e2e tests/e2e/test_orangehrm_live.py

Optional env vars:
    ORANGEHRM_BASE_URL - default https://opensource-demo.orangehrmlive.com
    ORANGEHRM_E2E_EMPLOYEE_NAME - employee to search; default "Emily Jones"
"""

import os
from dataclasses import dataclass

import pytest

from portal_automation.core.browser import BrowserManager
from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.orangehrm.pages import OrangeHrmPages
from portal_automation.portals.orangehrm.workflow import FindStatus

pytestmark = pytest.mark.e2e


@dataclass
class ConfigStub:
    orangehrm_base_url: str = "https://opensource-demo.orangehrmlive.com"
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
        pytest.skip("Set RUN_LIVE_E2E=1 to run live OrangeHRM e2e tests.")


def _base_url() -> str:
    """Base url.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return os.environ.get(
        "ORANGEHRM_BASE_URL",
        "https://opensource-demo.orangehrmlive.com",
    )


def _e2e_employee_name() -> str:
    """E2e employee name.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return os.environ.get("ORANGEHRM_E2E_EMPLOYEE_NAME", "Emily Jones")


def _should_skip_live_portal_error(error: PortalError) -> bool:
    """Should skip live portal error.
    
    Args:
        error: Value supplied by the test or fixture for `error`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return error.reason in {
        ReasonCode.PORTAL_UNAVAILABLE,
        ReasonCode.PORTAL_TIMEOUT,
    }


def _skip_if_live_portal_unavailable(error: PortalError) -> None:
    """Skip if live portal unavailable.
    
    Args:
        error: Value supplied by the test or fixture for `error`.
    
    Returns:
        None. The test communicates success through assertions.
    
    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    if _should_skip_live_portal_error(error):
        pytest.skip(str(error))


def test_orangehrm_live_login_success() -> None:
    """Admin login should succeed and leave the login page."""
    _require_live_run()
    config = ConfigStub(orangehrm_base_url=_base_url())
    try:
        with BrowserManager(config) as session:
            pages = OrangeHrmPages(session.page, config)
            pages.login("Admin", "admin123")
    except PortalError as exc:
        _skip_if_live_portal_unavailable(exc)
        raise


def test_orangehrm_live_find_known_employee() -> None:
    """Searching for a known live employee should return found (not not_found)."""
    _require_live_run()
    config = ConfigStub(orangehrm_base_url=_base_url())
    employee_name = _e2e_employee_name()

    from portal_automation.portals.orangehrm.input_schema import (
        OrangeHrmEmployeeRecord,
        SalaryDetails,
    )

    first, *rest = employee_name.split(" ", 1)
    last = rest[0] if rest else ""
    record = OrangeHrmEmployeeRecord(
        employee_key="e2e-lookup",
        first_name=first,
        last_name=last,
        job_title="",
        employment_status="",
        salary=SalaryDetails(amount="", frequency="", details=""),
    )

    try:
        with BrowserManager(config) as session:
            pages = OrangeHrmPages(session.page, config)
            pages.login("Admin", "admin123")
            result = pages.find_employee_record(record)
    except PortalError as exc:
        _skip_if_live_portal_unavailable(exc)
        raise

    assert result.status in (FindStatus.FOUND, FindStatus.AMBIGUOUS), (
        f"Expected found/ambiguous for '{employee_name}', got {result.status}: {result.detail}"
    )


def test_orangehrm_live_find_nonexistent_employee_returns_not_found() -> None:
    """Searching for an obviously nonexistent name should return not_found."""
    _require_live_run()
    config = ConfigStub(orangehrm_base_url=_base_url())

    from portal_automation.portals.orangehrm.input_schema import (
        OrangeHrmEmployeeRecord,
        SalaryDetails,
    )

    record = OrangeHrmEmployeeRecord(
        employee_key="e2e-ghost",
        first_name="Xqzz",
        last_name="Nonexistent99",
        job_title="",
        employment_status="",
        salary=SalaryDetails(amount="", frequency="", details=""),
    )

    try:
        with BrowserManager(config) as session:
            pages = OrangeHrmPages(session.page, config)
            pages.login("Admin", "admin123")
            result = pages.find_employee_record(record)
    except PortalError as exc:
        _skip_if_live_portal_unavailable(exc)
        raise

    assert result.status is FindStatus.NOT_FOUND, (
        f"Expected not_found for nonexistent employee, got {result.status}"
    )
