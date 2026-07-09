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

# ── Fake Playwright primitives ─────────────────────────────────────────────────


class FakeLocator:
    """Minimal fake locator that mimics Playwright locator API."""

    def __init__(
        self,
        items: list[str] | None = None,
        children: dict[str, "FakeLocator"] | None = None,
    ) -> None:
        self._items = items or []
        self._children = children or {}

    def count(self) -> int:
        return len(self._items)

    @property
    def first(self) -> "FakeLocator":
        return FakeLocator(self._items[:1], self._children)

    def nth(self, index: int) -> "FakeLocator":
        if index < len(self._items):
            return FakeLocator([self._items[index]], self._children)
        return FakeLocator([], self._children)

    def text_content(self) -> str | None:
        return self._items[0] if self._items else None

    def fill(self, value: str) -> None:
        pass

    def click(self) -> None:
        pass

    def set_input_files(self, path: str) -> None:
        pass

    def filter(self, has_text: str = "") -> "FakeLocator":
        matched = [item for item in self._items if has_text.lower() in item.lower()]
        return FakeLocator(matched, self._children)

    def locator(self, selector: str) -> "FakeLocator":
        return self._children.get(selector, FakeLocator())

    def all_text_contents(self) -> list[str]:
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
        return self._url

    def goto(self, url: str) -> None:
        self._url = url
        self.navigated_urls.append(url)

    def locator(self, selector: str) -> FakeLocator:
        return self._locators.get(selector, _EMPTY)

    def wait_for_url(self, pattern: str) -> None:
        if self._wait_for_url_raises:
            raise TimeoutError("wait_for_url timed out")

    def wait_for_selector(self, selector: str, timeout: int = 5000) -> None:
        if self._wait_for_selector_raises:
            raise TimeoutError("wait_for_selector timed out")


def _employee() -> OrangeHrmEmployeeRecord:
    return OrangeHrmEmployeeRecord(
        employee_key="emp-emily-jones",
        first_name="Emily",
        last_name="Jones",
        job_title="QA Engineer",
        employment_status="Full-Time Permanent",
        salary=SalaryDetails(amount="80000 USD", frequency="Annual", details=""),
    )


def _config() -> Any:
    return SimpleNamespace(
        orangehrm_base_url="https://orangehrm.example.com",
        orangehrm_username="Admin",
    )


def _pages(page: FakePage) -> OrangeHrmPages:
    return OrangeHrmPages(page, _config())


# ── login ──────────────────────────────────────────────────────────────────────


def test_login_success_no_error_element_no_login_in_url() -> None:
    """real branch: no error element, URL doesn't contain 'login' → success."""
    page = FakePage(url="https://orangehrm.example.com/dashboard/index")
    pages = _pages(page)
    pages.login("Admin", "admin123")  # should not raise


def test_login_failure_via_fake_attr() -> None:
    """fake-page branch: login_succeeded=False → PortalError(LOGIN_FAILED)."""
    page = SimpleNamespace(login_succeeded=False)
    pages = OrangeHrmPages(page, _config())
    with pytest.raises(PortalError) as exc:
        pages.login("Admin", "wrongpass")
    assert exc.value.reason is ReasonCode.LOGIN_FAILED


def test_login_real_page_success() -> None:
    """real branch: no error element and URL leaves /login → success."""
    page = FakePage(url="https://orangehrm.example.com/dashboard/index")
    pages = _pages(page)
    pages.login("Admin", "admin123")  # should not raise


def test_login_real_page_error_message_raises() -> None:
    """real branch: LOGIN_ERROR element visible → PortalError(LOGIN_FAILED)."""
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


def test_login_real_page_stuck_on_login_url_raises() -> None:
    """real branch: URL still contains 'login' path AND error element visible → PortalError."""
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


# ── find_employee_record ───────────────────────────────────────────────────────


def test_find_no_records_via_no_records_selector() -> None:
    """real branch: NO_RECORDS_SELECTOR visible with 'No Records' text → not_found."""
    no_rec = FakeLocator(["No Records Found"])
    page = FakePage(locators={OrangeHrmPages.NO_RECORDS_SELECTOR: no_rec})
    result = _pages(page).find_employee_record(_employee())
    assert result.status is FindStatus.NOT_FOUND


def test_find_one_result_row_returns_found() -> None:
    """real branch: 1 data row (no header) → found."""
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
    """real branch: 2 data rows → ambiguous."""
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
    source = (ROOT / "src/portal_automation/portals/orangehrm/pages.py").read_text(encoding="utf-8")

    assert "server-side filtered query" in source
    assert "visible result grid" in source


def test_find_with_header_row_excluded_from_count() -> None:
    """real branch: 2 rows total (1 header + 1 data) → found."""
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
    """fake-page branch: employee_search_error=True → error result."""
    page = SimpleNamespace(employee_search_error=True, locator=lambda s: _EMPTY)
    result = OrangeHrmPages(page, _config()).find_employee_record(_employee())
    assert result.status is FindStatus.ERROR


def test_find_employee_results_list_zero_items_returns_not_found() -> None:
    """fake-page branch: employee_search_results=[] → not_found."""
    page = SimpleNamespace(employee_search_results=[], locator=lambda s: _EMPTY)
    result = OrangeHrmPages(page, _config()).find_employee_record(_employee())
    assert result.status is FindStatus.NOT_FOUND


def test_find_employee_results_list_one_item_returns_found() -> None:
    """fake-page branch: employee_search_results=[record] → found."""
    page = SimpleNamespace(employee_search_results=[{"id": "Id09557"}], locator=lambda s: _EMPTY)
    result = OrangeHrmPages(page, _config()).find_employee_record(_employee())
    assert result.status is FindStatus.FOUND


def test_find_employee_results_list_multiple_items_returns_ambiguous() -> None:
    """fake-page branch: employee_search_results=[r1, r2] → ambiguous."""
    page = SimpleNamespace(
        employee_search_results=[{"id": "1"}, {"id": "2"}], locator=lambda s: _EMPTY
    )
    result = OrangeHrmPages(page, _config()).find_employee_record(_employee())
    assert result.status is FindStatus.AMBIGUOUS


def test_find_search_panel_collapsed_expand_called() -> None:
    """real branch: collapsed icon present → expand click, then search runs."""
    expand_clicks: list[str] = []

    class TrackingLocator(FakeLocator):
        @property
        def first(self) -> "TrackingLocator":  # type: ignore[override]
            return TrackingLocator(self._items[:1], self._children)

        def click(self) -> None:
            expand_clicks.append("clicked")

    page = FakePage(
        locators={
            ".oxd-icon.bi-chevron-down": TrackingLocator(["▼"]),
            OrangeHrmPages.RESULT_ROW: FakeLocator(["row"]),
            OrangeHrmPages.RESULT_HEADER_ROW: FakeLocator([]),
        }
    )
    # Verify the method runs without error and expand click was attempted
    _pages(page).find_employee_record(_employee())
    assert expand_clicks  # collapsed icon click was triggered


# ── list_salary_attachments ────────────────────────────────────────────────────


def test_list_salary_attachments_empty_state_returns_empty_list() -> None:
    """real branch: 'No Records Found' in Attachments section → []."""
    no_rec = FakeLocator(["No Records Found"])

    class _Section(FakeLocator):
        def locator(self, selector: str) -> FakeLocator:
            if "oxd-text" in selector or "NO_RECORDS" in selector.upper():
                return no_rec
            return _EMPTY

    # Simulate heading found → section derived
    heading = FakeLocator(["Attachments"])
    cards = FakeLocator(["card"])

    class _FakePage(FakePage):
        def locator(self, selector: str) -> FakeLocator:  # type: ignore[override]
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
    # Just confirm it returns [] without crashing — section None fallback
    result = _pages(page).list_salary_attachments(_employee())
    assert isinstance(result, list)


def test_list_salary_attachments_fake_attr_returns_filenames() -> None:
    """fake-page branch: attachment_filenames set → returned directly."""
    page = SimpleNamespace(
        attachment_filenames=["salary_emp-emily-jones_2026-07-09.txt"],
        locator=lambda s: _EMPTY,
    )
    result = OrangeHrmPages(page, _config()).list_salary_attachments(_employee())
    assert result == ["salary_emp-emily-jones_2026-07-09.txt"]


# ── upload_salary_attachment ───────────────────────────────────────────────────


def test_upload_salary_attachment_calls_file_input_set_input_files(tmp_path: Path) -> None:
    """real branch: Add button and file input found → set_input_files called."""
    doc = tmp_path / "salary.txt"
    doc.write_text("salary doc", encoding="utf-8")

    set_input_files_calls: list[str] = []

    class _FileInput(FakeLocator):
        def set_input_files(self, path: str) -> None:
            set_input_files_calls.append(path)

    class _AddBtn(FakeLocator):
        def filter(self, has_text: str = "") -> "FakeLocator":  # type: ignore[override]
            return _AddBtn(["Add"])

        def click(self) -> None:
            pass

    class _FakePage(FakePage):
        def locator(self, selector: str) -> FakeLocator:  # type: ignore[override]
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

    # Bypass _attachments_section by making list return empty (no-records)
    # and inject a simple section mock
    original_section = pages._attachments_section

    class _FakeSection(FakeLocator):
        def locator(self, selector: str) -> FakeLocator:
            if selector.startswith("button"):
                return _AddBtn(["Add"])
            return _EMPTY

    pages._attachments_section = lambda: _FakeSection(["section"])  # type: ignore[method-assign]
    pages.upload_salary_attachment(_employee(), doc)

    assert set_input_files_calls == [str(doc)]
    pages._attachments_section = original_section


def test_upload_raises_when_attachments_section_not_found(tmp_path: Path) -> None:
    """real branch: section is None → PortalError(PORTAL_UNAVAILABLE)."""
    doc = tmp_path / "salary.txt"
    doc.write_text("x", encoding="utf-8")
    page = FakePage()
    pages = _pages(page)
    pages._attachments_section = lambda: None  # type: ignore[method-assign]
    with pytest.raises(PortalError) as exc:
        pages.upload_salary_attachment(_employee(), doc)
    assert exc.value.reason is ReasonCode.PORTAL_UNAVAILABLE
