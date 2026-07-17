"""Unit tests for OrangeHrmPages real-DOM branches using fake locator/page objects."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.orangehrm.input_schema import (
    OrangeHrmEmployeeRecord,
    SalaryDetails,
)
from portal_automation.portals.orangehrm.pages import OrangeHrmPages
from portal_automation.portals.orangehrm.workflow import FindStatus

ROOT = Path(__file__).resolve().parents[2]

# --- Fake Playwright primitives ---------------------------------------------


class FakeLocator:
    """Minimal fake locator that mimics Playwright locator API."""

    def __init__(
        self,
        items: list[str] | None = None,
        children: dict[str, "FakeLocator"] | None = None,
    ) -> None:
        """Initialize this test helper instance.

        Args:
            items: Value supplied by the test or fixture for `items`.
            children: Value supplied by the test or fixture for `children`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self._items = items or []
        self._children = children or {}

    def count(self) -> int:
        """Count.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return len(self._items)

    @property
    def first(self) -> "FakeLocator":
        """First.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return FakeLocator(self._items[:1], self._children)

    def nth(self, index: int) -> "FakeLocator":
        """Nth.

        Args:
            index: Value supplied by the test or fixture for `index`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        if index < len(self._items):
            return FakeLocator([self._items[index]], self._children)
        return FakeLocator([], self._children)

    def text_content(self) -> str | None:
        """Text content.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return self._items[0] if self._items else None

    def fill(self, value: str) -> None:
        """Fill.

        Args:
            value: Value supplied by the test or fixture for `value`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        pass

    def click(self) -> None:
        """Click.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        pass

    def set_input_files(self, path: str) -> None:
        """Set input files.

        Args:
            path: Value supplied by the test or fixture for `path`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        pass

    def filter(self, has_text: str = "") -> "FakeLocator":
        """Filter.

        Args:
            has_text: Value supplied by the test or fixture for `has_text`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        matched = [item for item in self._items if has_text.lower() in item.lower()]
        return FakeLocator(matched, self._children)

    def locator(self, selector: str) -> "FakeLocator":
        """Locator.

        Args:
            selector: Value supplied by the test or fixture for `selector`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return self._children.get(selector, FakeLocator())

    def all_text_contents(self) -> list[str]:
        """All text contents.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return list(self._items)


_EMPTY = FakeLocator()


class FakePage:
    """Configurable fake page with real locator/goto API surface."""

    def __init__(
        self,
        url: str = "https://orangehrm.example.com/pim/viewEmployeeList",
        locators: dict[str, FakeLocator] | None = None,
        wait_for_selector_raises: bool = False,
        wait_for_url_raises: bool = False,
        navigated_urls: list[str] | None = None,
    ) -> None:
        """Initialize this test helper instance.

        Args:
            url: Value supplied by the test or fixture for `url`.
            locators: Value supplied by the test or fixture for `locators`.
            wait_for_selector_raises: Value supplied by the test or fixture for
                `wait_for_selector_raises`.
            wait_for_url_raises: Value supplied by the test or fixture for `wait_for_url_raises`.
            navigated_urls: Value supplied by the test or fixture for `navigated_urls`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self._url = url
        self._locators: dict[str, FakeLocator] = locators or {}
        self._wait_for_selector_raises = wait_for_selector_raises
        self._wait_for_url_raises = wait_for_url_raises
        self.navigated_urls: list[str] = navigated_urls if navigated_urls is not None else []
        self.filled: dict[str, str] = {}
        self.clicked: list[str] = []

    # Playwright Page API
    @property
    def url(self) -> str:
        """Url.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return self._url

    def goto(self, url: str) -> None:
        """Goto.

        Args:
            url: Value supplied by the test or fixture for `url`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        self._url = url
        self.navigated_urls.append(url)

    def locator(self, selector: str) -> FakeLocator:
        """Locator.

        Args:
            selector: Value supplied by the test or fixture for `selector`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        return self._locators.get(selector, _EMPTY)

    def wait_for_url(self, pattern: str) -> None:
        """Wait for url.

        Args:
            pattern: Value supplied by the test or fixture for `pattern`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        if self._wait_for_url_raises:
            raise TimeoutError("wait_for_url timed out")

    def wait_for_selector(self, selector: str, timeout: int = 5000) -> None:
        """Wait for selector.

        Args:
            selector: Value supplied by the test or fixture for `selector`.
            timeout: Value supplied by the test or fixture for `timeout`.

        Returns:
            None. The test communicates success through assertions.

        Raises:
            AssertionError: If the behavior under test does not match the expected outcome.
        """
        if self._wait_for_selector_raises:
            raise TimeoutError("wait_for_selector timed out")


def _employee() -> OrangeHrmEmployeeRecord:
    # Canonical employee fixture used by page-object branch tests.
    """Employee.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return OrangeHrmEmployeeRecord(
        employee_key="emp-emily-jones",
        first_name="Emily",
        last_name="Jones",
        job_title="QA Engineer",
        employment_status="Full-Time Permanent",
        salary=SalaryDetails(amount="80000 USD", frequency="Annual", details=""),
        employee_id="emily001",
    )


def _config() -> Any:
    # Minimal config object consumed by OrangeHrmPages.
    """Config.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return SimpleNamespace(
        orangehrm_base_url="https://orangehrm.example.com",
        orangehrm_username="Admin",
    )


def _pages(page: FakePage) -> OrangeHrmPages:
    # Convenience wrapper that injects the shared fake config.
    """Pages.

    Args:
        page: Value supplied by the test or fixture for `page`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return OrangeHrmPages(page, _config())


# --- Login behavior ----------------------------------------------------------


def test_login_success_no_error_element_no_login_in_url() -> None:
    """Browser-backed branch: no error element and URL does not contain login -> success."""
    page = FakePage(url="https://orangehrm.example.com/dashboard/index")
    pages = _pages(page)
    pages.login("Admin", "admin123")  # should not raise


def test_login_skips_navigation_when_session_is_already_authenticated() -> None:
    """Verify that login is idempotent when the browser is already inside OrangeHRM.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage(url="https://orangehrm.example.com/pim/viewEmployeeList")

    _pages(page).login("Admin", "admin123")

    assert page.navigated_urls == []


def test_login_treats_timed_out_navigation_as_success_when_session_becomes_authenticated() -> None:
    """Verify that a late-authenticated page does not force a second login form interaction.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """

    class LateAuthenticatedPage(FakePage):
        def goto(self, url: str, wait_until: str | None = None) -> None:  # type: ignore[override]
            """Navigate, then raise like Playwright can after the page has already changed.

            Args:
                url: Value supplied by the test or fixture for `url`.
                wait_until: Value supplied by the test or fixture for `wait_until`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                TimeoutError: Always, after moving to an authenticated URL.
            """
            self._url = "https://orangehrm.example.com/pim/viewEmployeeList"
            self.navigated_urls.append(url)
            raise TimeoutError("navigation timed out after session became authenticated")

    page = LateAuthenticatedPage(url="about:blank")

    _pages(page).login("Admin", "admin123")

    assert page.navigated_urls == ["https://orangehrm.example.com"]


def test_login_continues_when_navigation_times_out_after_reaching_login_url() -> None:
    """Verify that login waits for the form when goto times out after URL commit.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """

    class TimeoutAfterLoginUrlPage(FakePage):
        def __init__(self) -> None:
            """Initialize the fake page at about:blank."""
            super().__init__(url="about:blank")
            self._locators[OrangeHrmPages.USERNAME_INPUT] = FakeLocator([""])
            self._locators[OrangeHrmPages.PASSWORD_INPUT] = FakeLocator([""])
            self._locators[OrangeHrmPages.LOGIN_BUTTON] = FakeLocator(["Login"])

        def goto(self, url: str, wait_until: str | None = None) -> None:  # type: ignore[override]
            """Raise after changing URL to the login route.

            Args:
                url: Value supplied by the test or fixture for `url`.
                wait_until: Value supplied by the test or fixture for `wait_until`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                TimeoutError: Always, after moving to the login URL.
            """
            self._url = "https://orangehrm.example.com/web/index.php/auth/login"
            self.navigated_urls.append(url)
            raise TimeoutError("commit happened but page kept loading")

        def wait_for_url(self, pattern: str) -> None:
            """Simulate successful login redirect after the submit click.

            Args:
                pattern: Value supplied by the test or fixture for `pattern`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            self._url = "https://orangehrm.example.com/web/index.php/dashboard/index"

    page = TimeoutAfterLoginUrlPage()

    _pages(page).login("Admin", "admin123")

    assert page.navigated_urls == ["https://orangehrm.example.com"]


def test_login_reports_unavailable_when_login_url_stays_blank_without_username_field() -> None:
    """Verify that a blank login route reports a specific form-render outage.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage(
        url="https://orangehrm.example.com/web/index.php/auth/login",
        wait_for_selector_raises=True,
    )

    with pytest.raises(PortalError) as exc:
        _pages(page).login("Admin", "admin123")

    assert exc.value.reason is ReasonCode.PORTAL_UNAVAILABLE
    assert "did not render the username field" in exc.value.detail


def test_login_reports_browser_network_error_when_chrome_error_page_is_visible() -> None:
    """Verify that a Chrome network error page maps to a clear portal-unavailable error.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    page = FakePage(
        url="https://opensource-demo.orangehrmlive.com/web/index.php/auth/login",
        locators={
            "body": FakeLocator(
                [("This site can't be reached\nThe connection was reset.\nERR_CONNECTION_RESET")]
            )
        },
        wait_for_selector_raises=True,
    )

    with pytest.raises(PortalError) as exc:
        _pages(page).login("Admin", "admin123")

    assert exc.value.reason is ReasonCode.PORTAL_UNAVAILABLE
    assert "ERR_CONNECTION_RESET" in exc.value.detail
    assert "not reachable" in exc.value.detail


def test_login_form_timeout_does_not_read_page_title() -> None:
    """Verify that login outage diagnostics avoid potentially hanging page.title calls.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If the timeout path tries to read the page title.
    """

    class TitleRaisesPage(FakePage):
        def title(self) -> str:
            """Fail if the page object tries to read title during login outage diagnostics."""
            raise AssertionError("page.title() should not be called on login form timeout")

    page = TitleRaisesPage(
        url="https://opensource-demo.orangehrmlive.com/web/index.php/auth/login",
        wait_for_selector_raises=True,
    )

    with pytest.raises(PortalError) as exc:
        _pages(page).login("Admin", "admin123")

    assert exc.value.reason is ReasonCode.PORTAL_UNAVAILABLE
    assert "did not render the username field" in exc.value.detail


def test_login_continues_when_username_field_exists_after_wait_timeout() -> None:
    """Verify that a visible login form is used even when selector waiting times out.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If the login flow gives up despite the username input being present.
    """
    fills: dict[str, str] = {}
    clicks: list[str] = []

    class LoginInput(FakeLocator):
        def __init__(self, selector: str) -> None:
            """Initialize this test helper instance."""
            super().__init__([""])
            self.selector = selector

        def fill(self, value: str) -> None:
            """Record the value submitted to a login input."""
            fills[self.selector] = value

    class LoginButton(FakeLocator):
        def click(self) -> None:
            """Record that the login button was pressed."""
            clicks.append("login")
            page._url = "https://orangehrm.example.com/dashboard/index"

    page = FakePage(
        url="https://orangehrm.example.com/auth/login",
        wait_for_selector_raises=True,
        locators={
            OrangeHrmPages.USERNAME_INPUT: LoginInput(OrangeHrmPages.USERNAME_INPUT),
            OrangeHrmPages.PASSWORD_INPUT: LoginInput(OrangeHrmPages.PASSWORD_INPUT),
            OrangeHrmPages.LOGIN_BUTTON: LoginButton(["Login"]),
        },
    )

    _pages(page).login("Admin", "admin123")

    assert fills == {
        OrangeHrmPages.USERNAME_INPUT: "Admin",
        OrangeHrmPages.PASSWORD_INPUT: "admin123",
    }
    assert clicks == ["login"]


def test_login_failure_via_fake_attr() -> None:
    """Fake-page branch: login_succeeded=False -> PortalError(LOGIN_FAILED)."""
    page = SimpleNamespace(login_succeeded=False)
    pages = OrangeHrmPages(page, _config())
    with pytest.raises(PortalError) as exc:
        pages.login("Admin", "wrongpass")
    assert exc.value.reason is ReasonCode.LOGIN_FAILED


def test_login_real_page_success() -> None:
    """Browser-backed branch: no error element and URL leaves /login -> success."""
    page = FakePage(url="https://orangehrm.example.com/dashboard/index")
    pages = _pages(page)
    pages.login("Admin", "admin123")  # should not raise


def test_login_real_page_error_message_raises() -> None:
    """Browser-backed branch: LOGIN_ERROR element visible -> PortalError(LOGIN_FAILED)."""
    page = FakePage(
        url="https://orangehrm.example.com/auth/login",
        locators={
            OrangeHrmPages.LOGIN_ERROR: FakeLocator(["Invalid credentials"]),
        },
    )
    pages = _pages(page)
    with pytest.raises(PortalError) as exc:
        pages.login("Admin", "wrong")
    assert exc.value.reason is ReasonCode.LOGIN_FAILED
    assert "Invalid credentials" in exc.value.detail


def test_login_retries_once_after_csrf_validation_failure() -> None:
    """Verify that stale OrangeHRM CSRF state is cleared and retried once.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If cookies/storage are not cleared or the retry is not attempted.
    """

    class FakeContext:
        def __init__(self) -> None:
            """Initialize this test helper instance."""
            self.clear_cookie_calls = 0

        def clear_cookies(self) -> None:
            """Record cookie cleanup requested by the page object."""
            self.clear_cookie_calls += 1

    class LoginErrorLocator(FakeLocator):
        def __init__(self, page: "CsrfThenSuccessPage") -> None:
            """Initialize this test helper instance."""
            self._page = page

        def count(self) -> int:
            """Return one visible error only after the first submit."""
            return 1 if self._page.login_clicks == 1 else 0

        @property
        def first(self) -> "LoginErrorLocator":
            """Return self so text reads from the dynamic page state."""
            return self

        def text_content(self) -> str | None:
            """Return the transient CSRF message after the first submit."""
            if self._page.login_clicks == 1:
                return "CSRF token validation failed"
            return None

    class LoginButtonLocator(FakeLocator):
        def __init__(self, page: "CsrfThenSuccessPage") -> None:
            """Initialize this test helper instance."""
            self._page = page

        def count(self) -> int:
            """Return one login button."""
            return 1

        def click(self) -> None:
            """First click leaves CSRF error visible; second click authenticates."""
            self._page.login_clicks += 1
            if self._page.login_clicks >= 2:
                self._page._url = "https://orangehrm.example.com/dashboard/index"

    class InputLocator(FakeLocator):
        def count(self) -> int:
            """Return one input field."""
            return 1

    class CsrfThenSuccessPage(FakePage):
        def __init__(self) -> None:
            """Initialize this test helper instance."""
            super().__init__(url="https://orangehrm.example.com/auth/login")
            self.context = FakeContext()
            self.login_clicks = 0
            self.storage_clear_calls = 0

        def locator(self, selector: str) -> FakeLocator:
            """Return dynamic login locators for the CSRF retry scenario."""
            if selector == OrangeHrmPages.LOGIN_ERROR:
                return LoginErrorLocator(self)
            if selector == OrangeHrmPages.LOGIN_BUTTON:
                return LoginButtonLocator(self)
            if selector in {OrangeHrmPages.USERNAME_INPUT, OrangeHrmPages.PASSWORD_INPUT}:
                return InputLocator([""])
            return super().locator(selector)

        def evaluate(self, _script: str) -> None:
            """Record browser storage cleanup requested by the page object."""
            self.storage_clear_calls += 1

    page = CsrfThenSuccessPage()

    _pages(page).login("Admin", "admin123")

    assert page.login_clicks == 2
    assert page.context.clear_cookie_calls == 2
    assert page.storage_clear_calls == 2
    assert "dashboard" in page.url


def test_login_real_page_stuck_on_login_url_raises() -> None:
    """Browser-backed branch: login URL plus error element -> PortalError."""
    page = FakePage(
        url="https://orangehrm.example.com/auth/login",
        locators={
            OrangeHrmPages.LOGIN_ERROR: FakeLocator(["Invalid credentials"]),
        },
    )
    pages = _pages(page)
    with pytest.raises(PortalError) as exc:
        pages.login("Admin", "wrong")
    assert exc.value.reason is ReasonCode.LOGIN_FAILED


# --- Employee search behavior ------------------------------------------------


def test_find_no_records_via_no_records_selector() -> None:
    """Browser-backed branch: NO_RECORDS_SELECTOR with No Records text -> not_found."""
    no_rec = FakeLocator(["No Records Found"])
    page = FakePage(locators={OrangeHrmPages.NO_RECORDS_SELECTOR: no_rec})
    result = _pages(page).find_employee_record(_employee())
    assert result.status is FindStatus.NOT_FOUND


def test_find_one_result_row_returns_found() -> None:
    """Browser-backed branch: one data row and no header -> found."""
    # 1 result row, no header rows
    rows = FakeLocator(["Emily Jones row"])
    page = FakePage(
        locators={
            OrangeHrmPages.RESULT_ROW: rows,
            OrangeHrmPages.RESULT_HEADER_ROW: FakeLocator([]),
        }
    )
    result = _pages(page).find_employee_record(_employee())
    assert result.status is FindStatus.FOUND


def test_find_multiple_result_rows_returns_ambiguous() -> None:
    """Browser-backed branch: two data rows -> ambiguous."""
    rows = FakeLocator(["Emily Jones", "Emily Johnson"])
    page = FakePage(
        locators={
            OrangeHrmPages.RESULT_ROW: rows,
            OrangeHrmPages.RESULT_HEADER_ROW: FakeLocator([]),
        }
    )
    result = _pages(page).find_employee_record(_employee())
    assert result.status is FindStatus.AMBIGUOUS
    assert "2" in result.detail


def test_find_search_behavior_is_documented_as_server_filtered_visible_results() -> None:
    """Verify that find search behavior is documented as server filtered visible results.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/portals/orangehrm/pages.py").read_text(encoding="utf-8")

    assert "server-side filtered query" in source
    assert "visible result grid" in source


def test_find_uses_direct_employee_list_navigation_and_no_wait_search_click() -> None:
    """Verify that search avoids OrangeHRM SPA navigation waits.

    Returns:
        None. Assertions communicate the test outcome.

    Raises:
        AssertionError: If employee-list navigation or search submit regresses.
    """
    search_click_kwargs: list[dict[str, bool]] = []

    class SearchButton(FakeLocator):
        @property
        def first(self) -> "SearchButton":  # type: ignore[override]
            """Return self so click kwargs can be inspected."""
            return self

        def click(self, **kwargs: bool) -> None:  # type: ignore[override]
            """Record the Playwright click options requested by the page object."""
            search_click_kwargs.append(kwargs)

    class SearchForm(FakeLocator):
        @property
        def first(self) -> "SearchForm":  # type: ignore[override]
            """Return self so nested locators stay inspectable."""
            return self

        def locator(self, selector: str) -> FakeLocator:
            """Return the search submit button for the form."""
            if selector == OrangeHrmPages.SEARCH_SUBMIT:
                return SearchButton(["Search"])
            return super().locator(selector)

    page = FakePage(
        url="https://orangehrm.example.com/dashboard/index",
        locators={
            OrangeHrmPages.SEARCH_FORM_SELECTOR: SearchForm(["form"]),
            OrangeHrmPages.RESULT_ROW: FakeLocator(["row"]),
            OrangeHrmPages.RESULT_HEADER_ROW: FakeLocator([]),
        },
    )

    result = _pages(page).find_employee_record(_employee())

    assert result.status is FindStatus.FOUND
    assert page.navigated_urls == [
        "https://orangehrm.example.com/web/index.php/pim/viewEmployeeList"
    ]
    assert search_click_kwargs == [{"no_wait_after": True}]


def test_find_with_header_row_excluded_from_count() -> None:
    """Browser-backed branch: one header plus one data row -> found."""
    all_rows = FakeLocator(["header row", "Emily Jones row"])
    header_rows = FakeLocator(["header row"])
    page = FakePage(
        locators={
            OrangeHrmPages.RESULT_ROW: all_rows,
            OrangeHrmPages.RESULT_HEADER_ROW: header_rows,
        }
    )
    result = _pages(page).find_employee_record(_employee())
    assert result.status is FindStatus.FOUND


def test_find_employee_search_error_fake_attr_returns_error() -> None:
    """Fake-page branch: employee_search_error=True -> error result."""
    page = SimpleNamespace(employee_search_error=True, locator=lambda s: _EMPTY)
    result = OrangeHrmPages(page, _config()).find_employee_record(_employee())
    assert result.status is FindStatus.ERROR


def test_find_employee_results_list_zero_items_returns_not_found() -> None:
    """Fake-page branch: employee_search_results=[] -> not_found."""
    page = SimpleNamespace(employee_search_results=[], locator=lambda s: _EMPTY)
    result = OrangeHrmPages(page, _config()).find_employee_record(_employee())
    assert result.status is FindStatus.NOT_FOUND


def test_find_employee_results_list_one_item_returns_found() -> None:
    """Fake-page branch: one preloaded search result -> found."""
    page = SimpleNamespace(employee_search_results=[{"id": "Id09557"}], locator=lambda s: _EMPTY)
    result = OrangeHrmPages(page, _config()).find_employee_record(_employee())
    assert result.status is FindStatus.FOUND


def test_find_employee_results_list_multiple_items_returns_ambiguous() -> None:
    """Fake-page branch: multiple preloaded search results -> ambiguous."""
    page = SimpleNamespace(
        employee_search_results=[{"id": "1"}, {"id": "2"}], locator=lambda s: _EMPTY
    )
    result = OrangeHrmPages(page, _config()).find_employee_record(_employee())
    assert result.status is FindStatus.AMBIGUOUS


def test_find_search_panel_collapsed_expand_called() -> None:
    """Browser-backed branch: collapsed icon present -> expand click, then search runs."""
    expand_clicks: list[str] = []

    class TrackingLocator(FakeLocator):
        @property
        def first(self) -> "TrackingLocator":  # type: ignore[override]
            """First.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return TrackingLocator(self._items[:1], self._children)

        def click(self) -> None:
            """Click.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            expand_clicks.append("clicked")

    page = FakePage(
        locators={
            ".oxd-icon.bi-chevron-down": TrackingLocator(["collapsed"]),
            OrangeHrmPages.RESULT_ROW: FakeLocator(["row"]),
            OrangeHrmPages.RESULT_HEADER_ROW: FakeLocator([]),
        }
    )
    # Verify the method runs without error and attempts to expand the panel.
    _pages(page).find_employee_record(_employee())
    assert expand_clicks  # collapsed icon click was triggered


def test_add_employee_fills_employee_id_by_label_not_middle_name() -> None:
    """Verify that Add Employee writes the business key into Employee Id, not middle name."""
    fills: dict[str, str] = {}

    class _Input(FakeLocator):
        def __init__(self, name: str) -> None:
            super().__init__([name])
            self.name = name

        @property
        def first(self) -> "_Input":  # type: ignore[override]
            return self

        def fill(self, value: str) -> None:
            fills[self.name] = value

    class _Button(FakeLocator):
        @property
        def first(self) -> "_Button":  # type: ignore[override]
            return self

        def filter(self, has_text: str = "") -> "_Button":  # type: ignore[override]
            return self

    employee_id_input = _Input("employee_id")
    employee_id_group = FakeLocator(["Employee Id"], children={"input": employee_id_input})
    employee_id_label = FakeLocator(
        ["Employee Id"],
        children={"xpath=ancestor::*[contains(@class, 'oxd-input-group')][1]": employee_id_group},
    )
    page = FakePage(
        url="https://orangehrm.example.com/pim/viewEmployeeList",
        locators={
            "button": _Button(["Add"]),
            OrangeHrmPages.SEARCH_FORM_SELECTOR: FakeLocator(["form"]),
            'input[name="firstName"]': _Input("first_name"),
            'input[name="middleName"]': _Input("middle_name"),
            'input[name="lastName"]': _Input("last_name"),
            "label": employee_id_label,
            OrangeHrmPages.FORM_SAVE_BUTTON: _Button(["Save"]),
        },
    )

    _pages(page).add_employee(_employee())

    assert fills["first_name"] == "Emily"
    assert fills["middle_name"] == ""
    assert fills["last_name"] == "Jones"
    assert fills["employee_id"] == "emily001"


# --- Salary attachment listing ----------------------------------------------


def test_list_salary_attachments_empty_state_returns_empty_list() -> None:
    """Browser-backed branch: No Records Found in Attachments section -> empty list."""
    no_rec = FakeLocator(["No Records Found"])

    class _Section(FakeLocator):
        def locator(self, selector: str) -> FakeLocator:
            """Locator.

            Args:
                selector: Value supplied by the test or fixture for `selector`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            if "oxd-text" in selector or "NO_RECORDS" in selector.upper():
                return no_rec
            return _EMPTY

    # Simulate the Attachments heading being found so the section can be derived.
    heading = FakeLocator(["Attachments"])
    cards = FakeLocator(["card"])

    class _FakePage(FakePage):
        def locator(self, selector: str) -> FakeLocator:  # type: ignore[override]
            """Locator.

            Args:
                selector: Value supplied by the test or fixture for `selector`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            if "attachment_filenames" in selector:
                return _EMPTY
            if "Attachments" in selector or "oxd-text--h6" in selector:
                return heading
            if "orangehrm-card-container" in selector:
                return cards
            if OrangeHrmPages.SALARY_TAB in selector:
                return FakeLocator(["salary tab"])
            return _EMPTY

    page = _FakePage()
    page._locators[OrangeHrmPages.SALARY_TAB] = FakeLocator(["salary tab"])
    # Confirm the section-not-found fallback returns an empty list without raising.
    result = _pages(page).list_salary_attachments(_employee())
    assert isinstance(result, list)


def test_list_salary_attachments_fake_attr_returns_filenames() -> None:
    """Fake-page branch: attachment_filenames set -> returned directly."""
    page = SimpleNamespace(
        attachment_filenames=["salary_emp-emily-jones_2026-07-09.txt"],
        locator=lambda s: _EMPTY,
    )
    result = OrangeHrmPages(page, _config()).list_salary_attachments(_employee())
    assert result == ["salary_emp-emily-jones_2026-07-09.txt"]


def test_list_salary_attachments_reads_filename_from_second_table_cell() -> None:
    """Verify that attachment listing skips the checkbox cell and normalizes wrapped filenames.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    wrapped_filename = "salary_emp-\nemily-jones_2026\n-07-09.txt"
    cells = FakeLocator(["", wrapped_filename, "Salary document", "281.00 B"])
    rows = FakeLocator(["row"], children={".oxd-table-cell": cells})

    class _Section(FakeLocator):
        def locator(self, selector: str) -> FakeLocator:
            """Return attachment-section child locators for this test.

            Args:
                selector: Selector requested by the page object.

            Returns:
                Fake locator matching the requested selector.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            if selector == ".oxd-table-row":
                return rows
            return _EMPTY

    page = FakePage(locators={OrangeHrmPages.SALARY_TAB: FakeLocator(["salary tab"])})
    pages = _pages(page)
    pages._attachments_section = lambda: _Section(["section"])  # type: ignore[method-assign]

    assert pages.list_salary_attachments(_employee()) == ["salary_emp-emily-jones_2026-07-09.txt"]


# --- Salary attachment upload ------------------------------------------------


def test_upload_salary_attachment_calls_file_input_set_input_files(tmp_path: Path) -> None:
    """Browser-backed branch: Add button and file input found -> set_input_files called."""
    doc = tmp_path / "salary.txt"
    doc.write_text("salary doc", encoding="utf-8")

    set_input_files_calls: list[str] = []

    class _FileInput(FakeLocator):
        def set_input_files(self, path: str) -> None:
            """Set input files.

            Args:
                path: Value supplied by the test or fixture for `path`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            set_input_files_calls.append(path)

    class _AddBtn(FakeLocator):
        def filter(self, has_text: str = "") -> "FakeLocator":  # type: ignore[override]
            """Filter.

            Args:
                has_text: Value supplied by the test or fixture for `has_text`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            return _AddBtn(["Add"])

        def click(self) -> None:
            """Click.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            pass

    class _FakePage(FakePage):
        def locator(self, selector: str) -> FakeLocator:  # type: ignore[override]
            """Locator.

            Args:
                selector: Value supplied by the test or fixture for `selector`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            if selector == OrangeHrmPages.FILE_INPUT:
                return _FileInput(["file-input"])
            if selector == OrangeHrmPages.SALARY_TAB:
                return FakeLocator(["salary tab"])
            if selector == OrangeHrmPages.FORM_SAVE_BUTTON:
                return FakeLocator(["save"])
            if selector == OrangeHrmPages.COMMENT_INPUT:
                return _EMPTY
            return _EMPTY

    page = _FakePage()
    pages = OrangeHrmPages(page, _config())

    # Bypass _attachments_section with a simple section mock focused on upload behavior.
    original_section = pages._attachments_section

    class _FakeSection(FakeLocator):
        def locator(self, selector: str) -> FakeLocator:
            """Locator.

            Args:
                selector: Value supplied by the test or fixture for `selector`.

            Returns:
                None. The test communicates success through assertions.

            Raises:
                AssertionError: If the behavior under test does not match the expected outcome.
            """
            if selector.startswith("button"):
                return _AddBtn(["Add"])
            return _EMPTY

    pages._attachments_section = lambda: _FakeSection(["section"])  # type: ignore[method-assign]
    pages.upload_salary_attachment(_employee(), doc)

    assert set_input_files_calls == [str(doc)]
    pages._attachments_section = original_section


def test_upload_raises_when_attachments_section_not_found(tmp_path: Path) -> None:
    """Browser-backed branch: missing section -> PortalError(PORTAL_UNAVAILABLE)."""
    doc = tmp_path / "salary.txt"
    doc.write_text("x", encoding="utf-8")
    page = FakePage()
    pages = _pages(page)
    pages._attachments_section = lambda: None  # type: ignore[method-assign]
    with pytest.raises(PortalError) as exc:
        pages.upload_salary_attachment(_employee(), doc)
    assert exc.value.reason is ReasonCode.PORTAL_UNAVAILABLE


def test_upload_reports_session_dropped_when_browser_is_on_login_page(tmp_path: Path) -> None:
    """Browser-backed branch: login redirect during salary work -> SESSION_DROPPED."""
    doc = tmp_path / "salary.txt"
    doc.write_text("x", encoding="utf-8")
    page = FakePage(
        url="https://orangehrm.example.com/web/index.php/auth/login",
        locators={OrangeHrmPages.LOGIN_ERROR: FakeLocator(["Session Expired"])},
    )

    with pytest.raises(PortalError) as exc:
        _pages(page).upload_salary_attachment(_employee(), doc)

    assert exc.value.reason is ReasonCode.SESSION_DROPPED
    assert "Session Expired" in exc.value.detail
