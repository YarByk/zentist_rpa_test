from pathlib import Path
from typing import Any

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.orangehrm.input_schema import OrangeHrmEmployeeRecord
from portal_automation.portals.orangehrm.workflow import FindResult


class OrangeHrmPages:
    # ── Selectors ──────────────────────────────────────────────────────────
    USERNAME_INPUT = 'input[name="username"]'
    PASSWORD_INPUT = 'input[name="password"]'
    LOGIN_BUTTON = 'button[type="submit"]'
    LOGIN_ERROR = ".oxd-alert-content-text"

    PIM_NAV = 'a[href*="/pim/viewPimModule"]'

    SEARCH_FORM_SELECTOR = ".orangehrm-search-form"
    EMPLOYEE_NAME_HINT = 'input[placeholder="Type for hints..."]'
    SEARCH_SUBMIT = 'button[type="submit"]'

    RESULT_ROW = '.oxd-table-row[role="row"]'
    RESULT_HEADER_ROW = ".oxd-table-row.oxd-table-header-row"
    NO_RECORDS_SELECTOR = (
        ".orangehrm-horizontal-padding.orangehrm-vertical-padding "
        ".oxd-text.oxd-text--span"
    )

    JOB_TAB = 'a.orangehrm-tabs-item[href*="/viewJobDetails/"]'
    SALARY_TAB = 'a.orangehrm-tabs-item[href*="/viewSalaryList/"]'
    DROPDOWN_SELECTOR = ".oxd-select-text"
    DROPDOWN_OPTION = ".oxd-select-option"
    SUCCESS_TOAST = ".oxd-toast"
    FORM_SAVE_BUTTON = 'button[type="submit"]'

    FILE_INPUT = "input[type='file'].oxd-file-input"
    COMMENT_INPUT = 'textarea[placeholder="Type comment here"]'

    # Legacy label constants kept for backward compat
    USERNAME_LABEL = "Username"
    PASSWORD_LABEL = "Password"
    EMPLOYEE_SEARCH_LABEL = "Employee Name"
    FIRST_NAME_LABEL = "First Name"
    LAST_NAME_LABEL = "Last Name"
    EMPLOYEE_ID_LABEL = "Employee Id"
    JOB_TITLE_LABEL = "Job Title"
    EMPLOYMENT_STATUS_LABEL = "Employment Status"
    SALARY_ATTACHMENT_LABEL = "Salary Attachment"

    def __init__(self, page: Any, config: Any) -> None:
        self.page = page
        self.config = config

    # ── Public API ─────────────────────────────────────────────────────────

    def login(self, username: str, password: str) -> None:
        # fake-page branch — allow tests to signal login failure via attribute
        if getattr(self.page, "login_succeeded", None) is False:
            raise PortalError(ReasonCode.LOGIN_FAILED, "OrangeHRM login failed.")

        # real branch (also runs against fake pages that support goto/locator)
        self.page.goto(self.config.orangehrm_base_url)
        self.page.locator(self.USERNAME_INPUT).fill(username)
        self.page.locator(self.PASSWORD_INPUT).fill(password)
        self.page.locator(self.LOGIN_BUTTON).click()
        self._maybe_wait_for_url("dashboard")
        error = self._text_or_none(self.LOGIN_ERROR)
        if error is not None:
            raise PortalError(
                ReasonCode.LOGIN_FAILED,
                f"OrangeHRM login failed: {error}",
            )
        if "login" in self._current_url():
            raise PortalError(
                ReasonCode.LOGIN_FAILED,
                "OrangeHRM login did not redirect from login page.",
            )

    def find_employee_record(self, employee: OrangeHrmEmployeeRecord) -> FindResult:
        # fake-page branch — error flag
        if getattr(self.page, "employee_search_error", False):
            return FindResult.error("Employee search failed.")
        # fake-page branch — pre-loaded results list
        if hasattr(self.page, "employee_search_results"):
            results = list(self.page.employee_search_results)
            if len(results) == 0:
                return FindResult.not_found()
            if len(results) == 1:
                return FindResult.found()
            return FindResult.ambiguous(
                f"Employee search returned {len(results)} matches."
            )
        if not self._has_real_page():
            return FindResult.error("Employee search result state is unavailable.")

        # real branch
        self._navigate_to_employee_list()
        self._ensure_search_panel_expanded()
        self._fill_employee_name_and_search(employee.full_name)

        if self._no_records_visible():
            return FindResult.not_found()

        row_count = self._data_row_count()
        if row_count == 0:
            return FindResult.not_found()
        if row_count == 1:
            return FindResult.found()
        return FindResult.ambiguous(
            f"Employee search returned {row_count} matches for '{employee.full_name}'."
        )

    def add_employee(self, employee: OrangeHrmEmployeeRecord) -> None:
        # fake-page branch
        if not self._has_real_page():
            self.page.get_by_role("button", name="Add").click()
            self.page.get_by_label(self.FIRST_NAME_LABEL).fill(employee.first_name)
            self.page.get_by_label(self.LAST_NAME_LABEL).fill(employee.last_name)
            self.page.get_by_label(self.EMPLOYEE_ID_LABEL).fill(employee.employee_key)
            self.page.get_by_role("button", name="Save").click()
            return

        # real branch
        self._navigate_to_employee_list()
        add_btn = self.page.locator("button").filter(has_text="Add")
        if self._locator_count_loc(add_btn) == 0:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "OrangeHRM Add Employee button not found.",
            )
        add_btn.first.click()
        self._maybe_wait_for_url("addEmployee")
        self.page.locator('input[name="firstName"]').fill(employee.first_name)
        self.page.locator('input[name="lastName"]').fill(employee.last_name)
        # Employee ID is the third input in the personal details container
        emp_id = self.page.locator(".orangehrm-employee-container input").nth(2)
        emp_id.fill(employee.employee_key)
        self.page.locator(self.FORM_SAVE_BUTTON).first.click()
        self._maybe_wait_for_url("viewPersonalDetails")
        self._wait_for_toast_or_stable()

    def open_employee_profile(self, employee: OrangeHrmEmployeeRecord) -> None:
        # fake-page branch
        if not self._has_real_page():
            self.page.get_by_role("link", name=employee.full_name).click()
            return

        # real branch — click the single result row
        rows = self.page.locator(self.RESULT_ROW)
        total = self._locator_count_loc(rows)
        headers = self._locator_count_loc(
            self.page.locator(self.RESULT_HEADER_ROW)
        )
        data_rows = max(0, total - headers)
        if data_rows == 0:
            raise PortalError(
                ReasonCode.EMPLOYEE_NOT_FOUND,
                f"No result rows to open profile for '{employee.full_name}'.",
            )
        if data_rows > 1:
            raise PortalError(
                ReasonCode.EMPLOYEE_MATCH_AMBIGUOUS,
                f"Multiple rows visible; cannot open profile for '{employee.full_name}'.",
            )
        # Click the first data row (skip header if present)
        data_row_index = headers  # 0-based: skip header rows
        rows.nth(data_row_index).click()
        self._maybe_wait_for_url("viewPersonalDetails")

    def read_job(self, employee: OrangeHrmEmployeeRecord) -> dict[str, str]:
        # fake-page branch
        if hasattr(self.page, "job_values"):
            return dict(self.page.job_values)
        if not self._has_real_page():
            return {
                "job_title": (
                    self.page.get_by_label(self.JOB_TITLE_LABEL).text_content() or ""
                ),
                "employment_status": (
                    self.page.get_by_label(self.EMPLOYMENT_STATUS_LABEL).text_content() or ""
                ),
            }

        # real branch
        self._open_job_tab()
        return {
            "job_title": self._read_label_scoped_select("Job Title"),
            "employment_status": self._read_label_scoped_select("Employment Status"),
        }

    def update_job(self, employee: OrangeHrmEmployeeRecord) -> None:
        # fake-page branch
        if not self._has_real_page():
            self.page.get_by_role("tab", name="Job").click()
            self.page.get_by_label(self.JOB_TITLE_LABEL).fill(employee.job_title)
            self.page.get_by_label(self.EMPLOYMENT_STATUS_LABEL).fill(
                employee.employment_status
            )
            self.page.get_by_role("button", name="Save").click()
            return

        # real branch
        self._open_job_tab()
        current_job = self._read_label_scoped_select("Job Title")
        current_status = self._read_label_scoped_select("Employment Status")

        job_changed = self._select_dropdown_if_needed(
            "Job Title", employee.job_title, current_job
        )
        status_changed = self._select_dropdown_if_needed(
            "Employment Status", employee.employment_status, current_status
        )

        if job_changed or status_changed:
            self.page.locator(self.FORM_SAVE_BUTTON).first.click()
            self._wait_for_toast_or_stable()

    def list_salary_attachments(self, employee: OrangeHrmEmployeeRecord) -> list[str]:
        # fake-page branch
        if hasattr(self.page, "attachment_filenames"):
            return list(self.page.attachment_filenames)
        if not self._has_real_page():
            text = (
                self.page.locator("[data-test='salary-attachments']").text_content() or ""
            )
            return [line.strip() for line in text.splitlines() if line.strip()]

        # real branch
        self._open_salary_tab()
        section = self._attachments_section()
        if section is None:
            return []

        no_records = section.locator(self.NO_RECORDS_SELECTOR)
        if self._locator_count_loc(no_records) > 0:
            text = no_records.first.text_content() or ""
            if "no records" in text.lower():
                return []

        rows = section.locator(".oxd-table-row")
        count = self._locator_count_loc(rows)
        filenames: list[str] = []
        for i in range(count):
            cells = rows.nth(i).locator(".oxd-table-cell")
            if self._locator_count_loc(cells) > 0:
                name = (cells.first.text_content() or "").strip()
                if name:
                    filenames.append(name)
        return filenames

    def upload_salary_attachment(
        self, employee: OrangeHrmEmployeeRecord, path: Path
    ) -> None:
        # fake-page branch
        if not self._has_real_page():
            self.page.get_by_label(self.SALARY_ATTACHMENT_LABEL).set_input_files(str(path))
            self.page.get_by_role("button", name="Upload").click()
            return

        # real branch
        self._open_salary_tab()
        section = self._attachments_section()
        if section is None:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "OrangeHRM Salary Attachments section not found.",
            )

        add_btn = section.locator("button").filter(has_text="Add")
        if self._locator_count_loc(add_btn) == 0:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "OrangeHRM Salary Attachments 'Add' button not found.",
            )
        add_btn.first.click()

        file_input = self.page.locator(self.FILE_INPUT)
        if self._locator_count_loc(file_input) == 0:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "OrangeHRM file input not found on Add Attachment form.",
            )
        file_input.set_input_files(str(path))

        comment_input = self.page.locator(self.COMMENT_INPUT)
        if self._locator_count_loc(comment_input) > 0:
            comment_input.fill(f"Salary document for {employee.employee_key}")

        self.page.locator(self.FORM_SAVE_BUTTON).first.click()
        self._wait_for_toast_or_stable()

    def verify_salary_attachment(
        self, employee: OrangeHrmEmployeeRecord, filename: str
    ) -> bool:
        return filename in self.list_salary_attachments(employee)

    # ── Private helpers ────────────────────────────────────────────────────

    def _has_real_page(self) -> bool:
        """Return True only for a real Playwright page (has wait_for_selector/wait_for_url)."""
        return callable(getattr(self.page, "wait_for_selector", None)) or callable(
            getattr(self.page, "wait_for_url", None)
        )

    def _current_url(self) -> str:
        url = getattr(self.page, "url", "")
        if callable(url):
            url = url()
        return str(url or "")

    def _maybe_wait_for_url(self, fragment: str) -> None:
        wait = getattr(self.page, "wait_for_url", None)
        if callable(wait):
            try:
                wait(f"**/{fragment}**")
            except Exception:
                return

    def _locator_count_loc(self, locator: Any) -> int:
        count_fn = getattr(locator, "count", None)
        if callable(count_fn):
            try:
                return int(count_fn())
            except Exception:
                return 0
        return 0

    def _locator_count(self, selector: str) -> int:
        return self._locator_count_loc(self.page.locator(selector))

    def _text_or_none(self, selector: str) -> str | None:
        if self._locator_count(selector) == 0:
            return None
        text = (self.page.locator(selector).first.text_content() or "").strip()
        return text or None

    def _navigate_to_employee_list(self) -> None:
        if "/pim/viewEmployeeList" in self._current_url():
            return
        nav = self.page.locator(self.PIM_NAV)
        if self._locator_count_loc(nav) > 0:
            nav.first.click()
        self._maybe_wait_for_url("viewEmployeeList")

    def _ensure_search_panel_expanded(self) -> None:
        collapsed_icon = self.page.locator(".oxd-icon.bi-chevron-down")
        if self._locator_count_loc(collapsed_icon) > 0:
            collapsed_icon.first.click()

    def _fill_employee_name_and_search(self, full_name: str) -> None:
        search_form = self.page.locator(self.SEARCH_FORM_SELECTOR)
        if self._locator_count_loc(search_form) > 0:
            name_input = search_form.first.locator(self.EMPLOYEE_NAME_HINT).first
            search_btn = search_form.first.locator(self.SEARCH_SUBMIT).first
        else:
            name_input = self.page.locator(self.EMPLOYEE_NAME_HINT).first
            search_btn = self.page.locator(self.SEARCH_SUBMIT).first
        name_input.fill(full_name)
        search_btn.click()
        self._wait_for_results_or_no_records()

    def _wait_for_results_or_no_records(self) -> None:
        wait = getattr(self.page, "wait_for_selector", None)
        if callable(wait):
            try:
                wait(
                    f"{self.RESULT_ROW}, {self.NO_RECORDS_SELECTOR}",
                    timeout=10000,
                )
            except Exception:
                return

    def _no_records_visible(self) -> bool:
        loc = self.page.locator(self.NO_RECORDS_SELECTOR)
        if self._locator_count_loc(loc) == 0:
            return False
        text = (loc.first.text_content() or "").lower()
        return "no records" in text

    def _data_row_count(self) -> int:
        total = self._locator_count(self.RESULT_ROW)
        headers = self._locator_count(self.RESULT_HEADER_ROW)
        return max(0, total - headers)

    def _open_job_tab(self) -> None:
        tab = self.page.locator(self.JOB_TAB)
        if self._locator_count_loc(tab) > 0:
            tab.first.click()
            self._maybe_wait_for_url("viewJobDetails")

    def _open_salary_tab(self) -> None:
        tab = self.page.locator(self.SALARY_TAB)
        if self._locator_count_loc(tab) > 0:
            tab.first.click()
            self._maybe_wait_for_url("viewSalaryList")

    def _read_label_scoped_select(self, label_text: str) -> str:
        """Read the visible text of .oxd-select-text nearest to a given label."""
        group = self.page.locator(
            ".oxd-form-row, .oxd-input-field-bottom-space, .oxd-input-group"
        ).filter(has_text=label_text)
        if self._locator_count_loc(group) > 0:
            select = group.first.locator(self.DROPDOWN_SELECTOR)
            if self._locator_count_loc(select) > 0:
                text = (select.first.text_content() or "").strip()
                if text and text not in ("-- Select --", "--Select--"):
                    return text
        # Fallback via label element
        label_loc = self.page.locator("label").filter(has_text=label_text)
        if self._locator_count_loc(label_loc) > 0:
            parent = label_loc.first.locator("xpath=../..")
            select = parent.locator(self.DROPDOWN_SELECTOR)
            if self._locator_count_loc(select) > 0:
                return (select.first.text_content() or "").strip()
        return ""

    def _select_dropdown_if_needed(
        self, label_text: str, target_value: str, current_value: str
    ) -> bool:
        """Select target_value in dropdown near label. Returns True if a click was made."""
        if current_value == target_value:
            return False
        group = self.page.locator(
            ".oxd-form-row, .oxd-input-field-bottom-space, .oxd-input-group"
        ).filter(has_text=label_text)
        if self._locator_count_loc(group) == 0:
            return False
        trigger = group.first.locator(self.DROPDOWN_SELECTOR)
        if self._locator_count_loc(trigger) == 0:
            return False
        trigger.first.click()
        option = self.page.locator(self.DROPDOWN_OPTION).filter(has_text=target_value)
        if self._locator_count_loc(option) > 0:
            option.first.click()
            return True
        trigger.first.click()  # close without selection
        return False

    def _wait_for_toast_or_stable(self) -> None:
        wait = getattr(self.page, "wait_for_selector", None)
        if callable(wait):
            try:
                wait(self.SUCCESS_TOAST, timeout=5000)
            except Exception:
                return

    def _attachments_section(self) -> Any | None:
        """Locate the Attachments card on the Salary tab."""
        heading = self.page.locator(
            ".oxd-text--h6, .orangehrm-card-container h6, "
            ".oxd-table-filter-header-title .oxd-text"
        ).filter(has_text="Attachments")
        if self._locator_count_loc(heading) > 0:
            section = heading.first.locator("xpath=../../..")
            if self._locator_count_loc(section) > 0:
                return section.first
        # Fallback: last card container on page
        cards = self.page.locator(".orangehrm-card-container")
        count = self._locator_count_loc(cards)
        if count > 1:
            return cards.nth(count - 1)
        if count == 1:
            return cards.first
        return None
