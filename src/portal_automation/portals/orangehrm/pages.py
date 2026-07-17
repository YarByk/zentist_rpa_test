import os
from pathlib import Path
from typing import Any

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.orangehrm.input_schema import OrangeHrmEmployeeRecord
from portal_automation.portals.orangehrm.workflow import FindResult


class OrangeHrmPages:
    # --- Playwright selectors used by this page object ----------------------
    USERNAME_INPUT = 'input[name="username"]'
    PASSWORD_INPUT = 'input[name="password"]'
    LOGIN_BUTTON = 'button[type="submit"]'
    LOGIN_ERROR = ".oxd-alert-content-text"
    FIELD_ERROR = ".oxd-input-field-error-message"
    LOGIN_URL_FRAGMENT = "/auth/login"
    BROWSER_ERROR_MARKERS = (
        "this site can't be reached",
        "err_connection_reset",
        "err_connection_timed_out",
        "err_name_not_resolved",
        "dns_probe",
        "connection was reset",
    )

    PIM_NAV = 'a[href*="/pim/viewPimModule"]'

    SEARCH_FORM_SELECTOR = ".orangehrm-search-form"
    EMPLOYEE_NAME_HINT = 'input[placeholder="Type for hints..."]'
    SEARCH_SUBMIT = 'button[type="submit"]'

    RESULT_ROW = '.oxd-table-row[role="row"]'
    RESULT_DATA_ROW = ".oxd-table-card"
    RESULT_HEADER_ROW = ".oxd-table-row.oxd-table-header-row"
    NO_RECORDS_SELECTOR = (
        ".orangehrm-horizontal-padding.orangehrm-vertical-padding .oxd-text.oxd-text--span"
    )

    JOB_TAB = 'a.orangehrm-tabs-item[href*="/viewJobDetails/"]'
    SALARY_TAB = 'a.orangehrm-tabs-item[href*="/viewSalaryList/"]'
    DROPDOWN_SELECTOR = ".oxd-select-text"
    DROPDOWN_OPTION = ".oxd-select-option"
    SUCCESS_TOAST = ".oxd-toast"
    LOADING_SPINNER = ".oxd-loading-spinner"
    FORM_SAVE_BUTTON = 'button[type="submit"]'

    FILE_INPUT = "input[type='file'].oxd-file-input"
    COMMENT_INPUT = 'textarea[placeholder="Type comment here"]'
    SEARCH_FORM_TIMEOUT_MS = 5000
    SEARCH_RESULTS_TIMEOUT_MS = 5000
    JOB_DROPDOWN_TIMEOUT_MS = 6000
    LOGIN_FORM_TIMEOUT_MS = 6000
    SPINNER_TIMEOUT_MS = 3000
    TOAST_TIMEOUT_MS = 2500

    # Legacy label constants kept for fake page objects used in unit tests.
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
        """Create an OrangeHRM page adapter.

        Args:
            page: Playwright-like page object.
            config: Runtime config with OrangeHRM base URL.
        """
        self.page = page
        self.config = config
        self._matched_result_row_index: int | None = None

    # --- Public page-object API used by workflow.py -------------------------

    def login(self, username: str, password: str) -> None:
        """Log in to OrangeHRM.

        Args:
            username: OrangeHRM username.
            password: OrangeHRM password.

        Raises:
            PortalError: If login fails or remains on the login page.
        """
        # Unit-test doubles can signal login failure through a simple state flag.
        if getattr(self.page, "login_succeeded", None) is False:
            raise PortalError(ReasonCode.LOGIN_FAILED, "OrangeHRM login failed.")

        # Browser-backed flow: submit credentials and verify that login completed.
        if self._has_real_page() and self.is_authenticated():
            return
        if self._has_real_page():
            self._clear_login_session_state()
        self._login_from_fresh_page(username, password)

    def _login_from_fresh_page(self, username: str, password: str) -> None:
        """Submit the OrangeHRM login form from a clean login page.

        Args:
            username: OrangeHRM username.
            password: OrangeHRM password.

        Raises:
            PortalError: If login fails or remains on the login page.
        """
        self._goto_login_page()
        if self._has_real_page() and self.is_authenticated():
            return
        self._wait_for_login_form()
        self.page.locator(self.USERNAME_INPUT).fill(username)
        self.page.locator(self.PASSWORD_INPUT).fill(password)
        self.page.locator(self.LOGIN_BUTTON).click()
        self._maybe_wait_for_url("dashboard")
        error = self._text_or_none(self.LOGIN_ERROR)
        if error is not None:
            if self._is_csrf_login_error(error):
                self._debug("OrangeHRM rejected login with CSRF token validation; retrying once.")
                self._clear_login_session_state()
                self._goto_login_page()
                self._wait_for_login_form()
                self.page.locator(self.USERNAME_INPUT).fill(username)
                self.page.locator(self.PASSWORD_INPUT).fill(password)
                self.page.locator(self.LOGIN_BUTTON).click()
                self._maybe_wait_for_url("dashboard")
                error = self._text_or_none(self.LOGIN_ERROR)
                if error is None and "login" not in self._current_url():
                    return
            raise PortalError(
                ReasonCode.LOGIN_FAILED,
                f"OrangeHRM login failed: {error}",
            )
        if "login" in self._current_url():
            raise PortalError(
                ReasonCode.LOGIN_FAILED,
                "OrangeHRM login did not redirect from login page.",
            )

    def _is_csrf_login_error(self, error: str) -> bool:
        """Return whether a login error is the public-demo stale CSRF failure.

        Args:
            error: Login error text from the page.

        Returns:
            ``True`` when the error looks like OrangeHRM's CSRF validation message.
        """
        return "csrf token validation failed" in error.strip().lower()

    def _clear_login_session_state(self) -> None:
        """Clear stale OrangeHRM cookies and storage before submitting a fresh login.

        Persistent browser profiles keep history for operator review, but public OrangeHRM demo
        sessions can leave stale cookies/storage that make the next login form fail CSRF
        validation. Clearing session state only when a fresh login is needed preserves browser
        history while avoiding stale authentication tokens.
        """
        context = getattr(self.page, "context", None)
        clear_cookies = getattr(context, "clear_cookies", None)
        if callable(clear_cookies):
            try:
                clear_cookies()
            except Exception as exc:
                self._debug(f"Could not clear OrangeHRM cookies before login: {exc}")
        evaluate = getattr(self.page, "evaluate", None)
        if callable(evaluate):
            try:
                evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
            except Exception as exc:
                if "securityerror" in str(exc).lower():
                    return
                self._debug(f"Could not clear OrangeHRM browser storage before login: {exc}")

    def is_authenticated(self) -> bool:
        """Return whether the current page appears to be inside an authenticated session.

        Returns:
            ``True`` when the browser is already on an authenticated OrangeHRM page.
        """
        current_url = self._current_url().lower()
        if not current_url or current_url == "about:blank":
            return False
        if "login" in current_url:
            return False
        authenticated_fragments = (
            "/dashboard/",
            "/pim/",
            "/viewpimmodule",
            "/viewemployeelist",
            "/viewpersonaldetails",
        )
        if any(fragment in current_url for fragment in authenticated_fragments):
            return True
        try:
            return self._locator_count_loc(self.page.locator(self.PIM_NAV)) > 0
        except Exception:
            return False

    def find_employee_record(self, employee: OrangeHrmEmployeeRecord) -> FindResult:
        """Search for an employee and classify the visible result set.

        Args:
            employee: Employee record to search.

        Returns:
            Structured lookup result.
        """
        # Unit-test doubles may expose a precomputed search error.
        if getattr(self.page, "employee_search_error", False):
            return FindResult.error("Employee search failed.")
        # Unit-test doubles may also preload a deterministic search result list.
        if hasattr(self.page, "employee_search_results"):
            results = list(self.page.employee_search_results)
            if len(results) == 0:
                return FindResult.not_found()
            if len(results) == 1:
                return FindResult.found()
            return FindResult.ambiguous(f"Employee search returned {len(results)} matches.")
        if not self._has_real_page():
            return FindResult.error("Employee search result state is unavailable.")

        # Browser-backed flow: search in PIM and interpret the visible result grid strictly.
        # OrangeHRM submits employee search as a server-side filtered query.
        # After the query returns, the visible result grid is treated as the
        # authoritative filtered result set for this employee name. If multiple
        # rows remain visible, the workflow fails as ambiguous instead of
        # guessing or paging through unrelated directory data.
        self._raise_if_session_dropped("searching for an employee")
        self._navigate_to_employee_list()
        self._ensure_search_panel_expanded()
        self._matched_result_row_index = None
        self._fill_employee_search_fields_and_search(employee)

        if self._no_records_visible():
            return FindResult.not_found()

        row_count = self._data_row_count()
        if row_count == 0:
            return FindResult.not_found()
        if row_count == 1:
            return FindResult.found()
        matched_index = self._find_visible_row_index_by_employee_key(employee.portal_employee_id)
        if matched_index is not None:
            self._matched_result_row_index = matched_index
            self._debug(
                "Matched visible row for "
                f"employee_id={employee.portal_employee_id} at index={matched_index}."
            )
            return FindResult.found()
        return FindResult.ambiguous(
            f"Employee search returned {row_count} matches for '{employee.full_name}'."
        )

    def add_employee(self, employee: OrangeHrmEmployeeRecord) -> None:
        """Create an employee record.

        Args:
            employee: Employee record to create.

        Raises:
            PortalError: If required add-employee controls are not available.
        """
        # Unit-test doubles use semantic helpers; browser-backed runs drive the form directly.
        if not self._has_real_page():
            self.page.get_by_role("button", name="Add").click()
            self.page.get_by_label(self.FIRST_NAME_LABEL).fill(employee.first_name)
            self.page.get_by_label(self.LAST_NAME_LABEL).fill(employee.last_name)
            self.page.get_by_label(self.EMPLOYEE_ID_LABEL).fill(employee.portal_employee_id)
            self.page.get_by_role("button", name="Save").click()
            return

        # Browser-backed flow: open the Add Employee form and save the new profile.
        self._raise_if_session_dropped("adding an employee")
        self._navigate_to_employee_list()
        add_btn = self.page.locator("button").filter(has_text="Add")
        if self._locator_count_loc(add_btn) == 0:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "OrangeHRM Add Employee button not found.",
            )
        self._click_without_navigation_wait(add_btn.first)
        self._maybe_wait_for_url("addEmployee")
        self.page.locator('input[name="firstName"]').fill(employee.first_name)
        middle_name = self.page.locator('input[name="middleName"]')
        if self._locator_count_loc(middle_name) > 0:
            middle_name.first.fill("")
        self.page.locator('input[name="lastName"]').fill(employee.last_name)
        emp_id = self._input_for_label(self.EMPLOYEE_ID_LABEL)
        if emp_id is None:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                "OrangeHRM Employee Id input not found on Add Employee form.",
            )
        emp_id.fill(employee.portal_employee_id)
        self._click_without_navigation_wait(self.page.locator(self.FORM_SAVE_BUTTON).first)
        self._maybe_wait_for_url("viewPersonalDetails")
        self._wait_for_toast_or_stable()
        self._ensure_add_employee_saved(employee)
        self._debug_created_profile_state(employee)

    def open_employee_profile(self, employee: OrangeHrmEmployeeRecord) -> None:
        """Open the single visible employee profile result.

        Args:
            employee: Employee record used for error messages.

        Raises:
            PortalError: If no rows or multiple rows are visible.
        """
        # Open the profile only when the search result has narrowed down to one employee row.
        if not self._has_real_page():
            self.page.get_by_role("link", name=employee.full_name).click()
            return

        # Browser-backed flow: click the single visible data row.
        self._raise_if_session_dropped("opening an employee profile")
        rows = self.page.locator(self.RESULT_DATA_ROW)
        data_rows = self._locator_count_loc(rows)
        if data_rows == 0:
            raise PortalError(
                ReasonCode.EMPLOYEE_NOT_FOUND,
                f"No result rows to open profile for '{employee.full_name}'.",
            )
        if data_rows > 1 and self._matched_result_row_index is None:
            raise PortalError(
                ReasonCode.EMPLOYEE_MATCH_AMBIGUOUS,
                f"Multiple rows visible; cannot open profile for '{employee.full_name}'.",
            )
        row_index = self._matched_result_row_index or 0
        if row_index >= data_rows:
            raise PortalError(
                ReasonCode.EMPLOYEE_NOT_FOUND,
                f"Matched row for '{employee.full_name}' is no longer visible.",
            )
        rows.nth(row_index).click()
        self._maybe_wait_for_url("viewPersonalDetails")

    def read_job(self, employee: OrangeHrmEmployeeRecord) -> dict[str, str]:
        """Read current job values.

        Args:
            employee: Employee record associated with the current profile.

        Returns:
            Dictionary with ``job_title`` and ``employment_status``.
        """
        # Read the current Job tab state so the workflow can stay idempotent on reruns.
        if hasattr(self.page, "job_values"):
            return dict(self.page.job_values)
        if not self._has_real_page():
            return {
                "job_title": (self.page.get_by_label(self.JOB_TITLE_LABEL).text_content() or ""),
                "employment_status": (
                    self.page.get_by_label(self.EMPLOYMENT_STATUS_LABEL).text_content() or ""
                ),
            }

        # Browser-backed flow: read the selected values from the Job tab.
        self._raise_if_session_dropped("reading job details")
        self._open_job_tab()
        return {
            "job_title": self._read_label_scoped_select("Job Title"),
            "employment_status": self._read_label_scoped_select("Employment Status"),
        }

    def update_job(self, employee: OrangeHrmEmployeeRecord) -> None:
        """Update job fields when current values differ.

        Args:
            employee: Employee record containing target job values.
        """
        # Update the Job tab only when the visible values differ from the target record.
        if not self._has_real_page():
            self.page.get_by_role("tab", name="Job").click()
            self.page.get_by_label(self.JOB_TITLE_LABEL).fill(employee.job_title)
            self.page.get_by_label(self.EMPLOYMENT_STATUS_LABEL).fill(employee.employment_status)
            self.page.get_by_role("button", name="Save").click()
            return

        # Browser-backed flow: save only when at least one dropdown actually changes.
        self._raise_if_session_dropped("updating job details")
        self._open_job_tab()
        current_job = self._read_label_scoped_select("Job Title")
        current_status = self._read_label_scoped_select("Employment Status")

        job_changed = self._select_dropdown_if_needed("Job Title", employee.job_title, current_job)
        status_changed = self._select_dropdown_if_needed(
            "Employment Status", employee.employment_status, current_status
        )

        if job_changed or status_changed:
            self._click_without_navigation_wait(self.page.locator(self.FORM_SAVE_BUTTON).first)
            self._wait_for_toast_or_stable()

    def list_salary_attachments(self, employee: OrangeHrmEmployeeRecord) -> list[str]:
        """List salary attachment filenames.

        Args:
            employee: Employee record associated with the current profile.

        Returns:
            Visible salary attachment filenames.
        """
        # Return the current attachment filenames so duplicate salary uploads can be skipped.
        if hasattr(self.page, "attachment_filenames"):
            return list(self.page.attachment_filenames)
        if not self._has_real_page():
            text = self.page.locator("[data-test='salary-attachments']").text_content() or ""
            return [line.strip() for line in text.splitlines() if line.strip()]

        # Browser-backed flow: scrape attachment names from the Salary tab table.
        self._raise_if_session_dropped("listing salary attachments")
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
            name = self._salary_attachment_filename_from_row(rows.nth(i))
            if name:
                filenames.append(name)
        return filenames

    def upload_salary_attachment(self, employee: OrangeHrmEmployeeRecord, path: Path) -> None:
        """Upload a salary attachment file.

        Args:
            employee: Employee record associated with the current profile.
            path: Local file path to upload.

        Raises:
            PortalError: If the attachment section, add button, or file input is unavailable.
        """
        # Unit-test doubles handle uploads through simple file-input shims.
        if not self._has_real_page():
            self.page.get_by_label(self.SALARY_ATTACHMENT_LABEL).set_input_files(str(path))
            self.page.get_by_role("button", name="Upload").click()
            return

        # Browser-backed flow: open the attachment form, upload the file, and save it.
        self._raise_if_session_dropped("uploading a salary attachment")
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
        self._click_without_navigation_wait(add_btn.first)

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

        self._click_without_navigation_wait(self.page.locator(self.FORM_SAVE_BUTTON).first)
        self._wait_for_toast_or_stable()

    def verify_salary_attachment(self, employee: OrangeHrmEmployeeRecord, filename: str) -> bool:
        """Return whether a salary attachment filename is visible.

        Args:
            employee: Employee record associated with the current profile.
            filename: Expected attachment filename.

        Returns:
            ``True`` when the filename is listed.
        """
        expected = self._normalize_table_text(filename)
        visible = {
            self._normalize_table_text(name) for name in self.list_salary_attachments(employee)
        }
        return expected in visible

    # --- Private navigation and DOM helpers ---------------------------------

    def _has_real_page(self) -> bool:
        """Return True only for a real Playwright page (has wait_for_selector/wait_for_url)."""
        return callable(getattr(self.page, "wait_for_selector", None)) or callable(
            getattr(self.page, "wait_for_url", None)
        )

    def _current_url(self) -> str:
        """Return the current page URL as text.

        Returns:
            Current URL or an empty string.
        """
        url = getattr(self.page, "url", "")
        if callable(url):
            url = url()
        return str(url or "")

    def _maybe_wait_for_url(self, fragment: str) -> None:
        """Best-effort wait for a URL fragment.

        Args:
            fragment: URL fragment expected after navigation.
        """
        wait = getattr(self.page, "wait_for_url", None)
        if callable(wait):
            try:
                wait(f"**/{fragment}**")
            except Exception:
                return

    def _goto_or_raise(self, path: str, failure_message: str) -> None:
        """Navigate directly to an OrangeHRM route and classify browser errors.

        Args:
            path: Absolute OrangeHRM web path beginning with ``/``.
            failure_message: Human-readable prefix for timeout/unavailable errors.

        Raises:
            PortalError: If navigation fails and the browser is not still usable.
        """
        target_url = f"{self.config.orangehrm_base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            self.page.goto(target_url, wait_until="commit")
        except TypeError:
            try:
                self.page.goto(target_url)
            except Exception as exc:
                self._raise_navigation_error(failure_message, exc)
        except Exception as exc:
            self._raise_navigation_error(failure_message, exc)

    def _raise_navigation_error(self, failure_message: str, exc: Exception) -> None:
        """Raise a portal-domain navigation error unless the target page is usable.

        Args:
            failure_message: Human-readable error prefix.
            exc: Browser-driver exception.

        Raises:
            PortalError: If the browser shows a network error or the page is unusable.
        """
        browser_error = self._browser_error_summary()
        if browser_error:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                f"{failure_message}. {browser_error}; url={self._current_url()!r}",
            ) from exc
        self._debug(f"{failure_message}: {exc}")

    def _click_without_navigation_wait(self, locator: Any) -> None:
        """Click a locator without letting Playwright wait for OrangeHRM SPA navigation.

        Args:
            locator: Playwright-like locator to click.

        Raises:
            Exception: Any click failure from the browser driver.
        """
        try:
            locator.click(no_wait_after=True)
        except TypeError:
            locator.click()

    def _locator_count_loc(self, locator: Any) -> int:
        """Return a locator count while tolerating simplified fake locators.

        Args:
            locator: Playwright-like locator.

        Returns:
            Integer count, or ``0`` if counting fails.
        """
        count_fn = getattr(locator, "count", None)
        if callable(count_fn):
            try:
                return int(count_fn())
            except Exception:
                return 0
        return 0

    def _locator_count(self, selector: str) -> int:
        """Return the number of elements matching a selector.

        Args:
            selector: CSS selector.

        Returns:
            Locator count.
        """
        return self._locator_count_loc(self.page.locator(selector))

    def _text_or_none(self, selector: str) -> str | None:
        """Return stripped text for a selector, or ``None``.

        Args:
            selector: CSS selector.

        Returns:
            Stripped text, or ``None`` when no non-blank text exists.
        """
        if self._locator_count(selector) == 0:
            return None
        text = (self.page.locator(selector).first.text_content() or "").strip()
        return text or None

    def _all_text_for_selector(self, selector: str) -> list[str]:
        """Return all non-blank texts for a selector.

        Args:
            selector: CSS selector.

        Returns:
            Visible text values.
        """
        locator = self.page.locator(selector)
        all_texts = getattr(locator, "all_text_contents", None)
        if callable(all_texts):
            try:
                return [str(text).strip() for text in all_texts() if str(text).strip()]
            except Exception:
                return []
        values = []
        count = self._locator_count_loc(locator)
        for index in range(count):
            try:
                text = locator.nth(index).text_content() or ""
            except Exception:
                continue
            stripped = text.strip()
            if stripped:
                values.append(stripped)
        return values

    def _navigate_to_employee_list(self) -> None:
        """Navigate to the PIM employee list if not already there."""
        self._raise_if_session_dropped("navigating to the employee list")
        if "/pim/viewEmployeeList" in self._current_url():
            self._wait_for_employee_search_form()
            self._raise_if_session_dropped("waiting for the employee search form")
            return
        self._goto_or_raise(
            "/web/index.php/pim/viewEmployeeList",
            "OrangeHRM employee list navigation failed",
        )
        self._maybe_wait_for_url("viewEmployeeList")
        self._wait_for_page_stable()
        self._wait_for_employee_search_form()
        self._raise_if_session_dropped("navigating to the employee list")

    def _ensure_search_panel_expanded(self) -> None:
        """Expand the employee search panel when a collapsed icon is visible."""
        collapsed_icon = self.page.locator(".oxd-icon.bi-chevron-down")
        if self._locator_count_loc(collapsed_icon) > 0:
            collapsed_icon.first.click()

    def _fill_employee_search_fields_and_search(self, employee: OrangeHrmEmployeeRecord) -> None:
        """Fill stable employee search fields and submit the search.

        Args:
            employee: Employee record whose name and id should identify one row.
        """
        search_form = self.page.locator(self.SEARCH_FORM_SELECTOR)
        if self._locator_count_loc(search_form) > 0:
            form = search_form.first
            search_btn = form.locator(self.SEARCH_SUBMIT).first
        else:
            form = self.page
            search_btn = self.page.locator(self.SEARCH_SUBMIT).first
        self._fill_search_group_input(form, 0, employee.full_name)
        # Do not fill Employee Id with the business key: the public demo validates that field
        # as its own generated id and returns "Invalid Parameter" for our text key.
        self._click_without_navigation_wait(search_btn)
        self._wait_for_results_or_no_records()

    def _fill_search_group_input(self, scope: Any, group_index: int, value: str) -> None:
        """Fill an input by field-group position in the OrangeHRM search form.

        Args:
            scope: Locator or page object that contains the target form.
            group_index: Zero-based ``.oxd-input-group`` position.
            value: Text to enter into the field.
        """
        groups = scope.locator(".oxd-input-group")
        group_count = self._locator_count_loc(groups)
        self._debug(f"Search group index={group_index} group_count={group_count} value={value!r}.")
        if group_count <= group_index:
            return
        field = groups.nth(group_index).locator("input")
        count = self._locator_count_loc(field)
        self._debug(f"Search group index={group_index} input_count={count} value={value!r}.")
        if count == 0:
            return
        field.first.fill(value)

    def _wait_for_employee_search_form(self) -> None:
        """Best-effort wait until the employee search form exists."""
        wait = getattr(self.page, "wait_for_selector", None)
        if callable(wait):
            try:
                wait(self.SEARCH_FORM_SELECTOR, timeout=self.SEARCH_FORM_TIMEOUT_MS)
            except Exception:
                return
        self._raise_if_session_dropped("waiting for the employee search form")

    def _raise_if_session_dropped(self, action: str) -> None:
        """Raise a retryable session error when OrangeHRM redirects back to login.

        Args:
            action: Human-readable action that was about to run or just ran.

        Raises:
            PortalError: If the current browser URL is the OrangeHRM login route.
        """
        if not self._has_real_page() or not self._is_login_url():
            return
        error_text = self._text_or_none(self.LOGIN_ERROR)
        detail = f"OrangeHRM session dropped while {action}; url={self._current_url()!r}."
        if error_text:
            detail += f" Login page message: {error_text}."
        raise PortalError(ReasonCode.SESSION_DROPPED, detail)

    def _goto_login_page(self) -> None:
        """Navigate to the OrangeHRM login page using the lightest reliable load condition.

        Raises:
            PortalError: If navigation to the login page times out before the session is usable.
        """
        try:
            self.page.goto(self.config.orangehrm_base_url, wait_until="commit")
        except TypeError:
            try:
                self.page.goto(self.config.orangehrm_base_url)
            except Exception as exc:
                self._raise_login_navigation_error(exc)
        except Exception as exc:
            self._raise_login_navigation_error(exc)

    def _raise_login_navigation_error(self, exc: Exception) -> None:
        """Raise a portal-domain error unless the page is already authenticated.

        Args:
            exc: Navigation exception raised by the browser driver.

        Raises:
            PortalError: Always, unless the browser is already authenticated.
        """
        if self.is_authenticated():
            return
        browser_error = self._browser_error_summary()
        if browser_error:
            raise PortalError(
                ReasonCode.PORTAL_UNAVAILABLE,
                (
                    "OrangeHRM login page is not reachable. "
                    f"{browser_error}; url={self._current_url()!r}; title={self._page_title()!r}"
                ),
            ) from exc
        if self._is_login_url():
            self._debug(f"Login navigation raised an exception after reaching the login URL: {exc}")
            return
        raise PortalError(
            ReasonCode.PORTAL_TIMEOUT,
            f"OrangeHRM login page navigation failed: {exc}",
        ) from exc

    def _is_login_url(self) -> bool:
        """Return whether the current browser URL is the OrangeHRM login page.

        Returns:
            ``True`` when the URL looks like the login route.
        """
        return self.LOGIN_URL_FRAGMENT in self._current_url().lower()

    def _wait_for_login_form(self) -> None:
        """Wait until the OrangeHRM login form is actually rendered.

        Raises:
            PortalError: If the login route opens but the form never appears.
        """
        wait = getattr(self.page, "wait_for_selector", None)
        if callable(wait):
            try:
                wait(self.USERNAME_INPUT, timeout=self.LOGIN_FORM_TIMEOUT_MS)
                return
            except Exception as exc:
                if self._locator_count(self.USERNAME_INPUT) > 0:
                    self._debug(
                        "OrangeHRM username field exists after wait timeout; continuing login."
                    )
                    return
                browser_error = self._browser_error_summary()
                if browser_error:
                    raise PortalError(
                        ReasonCode.PORTAL_UNAVAILABLE,
                        (
                            "OrangeHRM login page is not reachable. "
                            f"{browser_error}; url={self._current_url()!r}"
                        ),
                    ) from exc
                raise PortalError(
                    ReasonCode.PORTAL_UNAVAILABLE,
                    (
                        "OrangeHRM login page opened but did not render the username field. "
                        f"url={self._current_url()!r}; error={exc}"
                    ),
                ) from exc
        return

    def _page_title(self) -> str:
        """Return the current page title when the page object exposes it.

        Returns:
            Current page title or an empty string.
        """
        title = getattr(self.page, "title", None)
        if not callable(title):
            return ""
        try:
            return str(title() or "")
        except Exception:
            return ""

    def _browser_error_summary(self) -> str:
        """Return a concise Chrome error-page summary when the browser shows one.

        Returns:
            Browser error summary, or an empty string when the page does not look like a Chrome
            network error page.
        """
        body_text = self._page_body_text()
        normalized = " ".join(body_text.lower().split())
        if not normalized:
            return ""
        if not any(marker in normalized for marker in self.BROWSER_ERROR_MARKERS):
            return ""
        lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        useful = [line for line in lines if "chrome is being controlled" not in line.lower()]
        return "browser_error=" + " | ".join(useful[:6])

    def _page_body_text(self) -> str:
        """Return visible body text when available.

        Returns:
            Body text, or an empty string when the page object cannot provide it.
        """
        try:
            body = self.page.locator("body")
        except Exception:
            return ""
        inner_text = getattr(body, "inner_text", None)
        if callable(inner_text):
            try:
                return str(inner_text(timeout=1000) or "")
            except TypeError:
                try:
                    return str(inner_text() or "")
                except Exception:
                    return ""
            except Exception:
                return ""
        text_content = getattr(body, "text_content", None)
        if callable(text_content):
            try:
                return str(text_content() or "")
            except Exception:
                return ""
        return ""

    def _debug_created_profile_state(self, employee: OrangeHrmEmployeeRecord) -> None:
        """Log the profile state reached immediately after Add Employee.

        Args:
            employee: Employee record that was just submitted.
        """
        first_name = self._first_input_value('input[name="firstName"]')
        last_name = self._first_input_value('input[name="lastName"]')
        employee_id = self._input_value_for_label(self.EMPLOYEE_ID_LABEL)
        self._debug(
            "Add Employee completed; "
            f"expected={employee.full_name!r}; "
            f"url={self._current_url()!r}; title={self._page_title()!r}; "
            f"first_name={first_name!r}; "
            f"last_name={last_name!r}; "
            f"employee_id={employee_id!r}."
        )

    def _input_value_for_label(self, label_text: str) -> str:
        """Return the current input value near a label for debug logging.

        Args:
            label_text: Visible label text.

        Returns:
            Input value or an empty string.
        """
        field = self._input_for_label(label_text)
        if field is None:
            return ""
        input_value = getattr(field, "input_value", None)
        if callable(input_value):
            try:
                return str(input_value(timeout=1000) or "")
            except TypeError:
                try:
                    return str(input_value() or "")
                except Exception:
                    return ""
            except Exception:
                return ""
        get_attribute = getattr(field, "get_attribute", None)
        if callable(get_attribute):
            try:
                return str(get_attribute("value") or "")
            except Exception:
                return ""
        return ""

    def _ensure_add_employee_saved(self, employee: OrangeHrmEmployeeRecord) -> None:
        """Raise a clear error when Add Employee remains on the form after save.

        Args:
            employee: Employee record that was submitted.

        Raises:
            PortalError: If OrangeHRM keeps the Add Employee form open with validation errors.
        """
        if "addemployee" not in self._current_url().lower():
            return
        validation_errors = self._all_text_for_selector(self.FIELD_ERROR)
        detail = "; ".join(validation_errors) if validation_errors else "profile did not open"
        raise PortalError(
            ReasonCode.VALIDATION_FAILED,
            (f"OrangeHRM Add Employee did not save '{employee.full_name}': {detail}."),
        )

    def _first_input_value(self, selector: str, index: int = 0) -> str:
        """Return an input value for debug logging.

        Args:
            selector: CSS selector for one or more input elements.
            index: Zero-based element index to read.

        Returns:
            Input value or an empty string when it cannot be read.
        """
        try:
            locator = self.page.locator(selector).nth(index)
            input_value = getattr(locator, "input_value", None)
            if callable(input_value):
                return str(input_value(timeout=1000) or "")
            value = getattr(locator, "get_attribute", None)
            if callable(value):
                return str(value("value") or "")
        except Exception:
            return ""
        return ""

    def _wait_for_results_or_no_records(self) -> None:
        """Best-effort wait for search results or the no-records message."""
        wait = getattr(self.page, "wait_for_selector", None)
        if callable(wait):
            try:
                wait(
                    f"{self.RESULT_ROW}, {self.NO_RECORDS_SELECTOR}",
                    timeout=self.SEARCH_RESULTS_TIMEOUT_MS,
                )
            except Exception:
                return

    def _no_records_visible(self) -> bool:
        """Return whether the no-records message is visible.

        Returns:
            ``True`` when visible text contains ``no records``.
        """
        loc = self.page.locator(self.NO_RECORDS_SELECTOR)
        if self._locator_count_loc(loc) == 0:
            return False
        text = (loc.first.text_content() or "").lower()
        return "no records" in text

    def _data_row_count(self) -> int:
        """Return result table data-row count excluding header rows.

        Returns:
            Non-negative data row count.
        """
        data_rows = self._locator_count(self.RESULT_DATA_ROW)
        if data_rows > 0:
            return data_rows
        total = self._locator_count(self.RESULT_ROW)
        headers = self._locator_count(self.RESULT_HEADER_ROW)
        return max(0, total - headers)

    def _find_visible_row_index_by_employee_key(self, employee_key: str) -> int | None:
        """Find the visible result row that contains a known employee key.

        Args:
            employee_key: Stable employee id created by the workflow.

        Returns:
            Zero-based data-card index when visible, otherwise ``None``.
        """
        rows = self.page.locator(self.RESULT_DATA_ROW)
        count = self._locator_count_loc(rows)
        for index in range(count):
            text = rows.nth(index).text_content() or ""
            if employee_key in text:
                return index
        return None

    def _open_job_tab(self) -> None:
        """Open the Job tab when the tab link is visible."""
        self._raise_if_session_dropped("opening the Job tab")
        tab = self.page.locator(self.JOB_TAB)
        if self._locator_count_loc(tab) > 0:
            tab.first.click()
            self._maybe_wait_for_url("viewJobDetails")
        self._wait_for_job_tab_ready()
        self._raise_if_session_dropped("opening the Job tab")

    def _open_salary_tab(self) -> None:
        """Open the Salary tab when the tab link is visible."""
        self._raise_if_session_dropped("opening the Salary tab")
        tab = self.page.locator(self.SALARY_TAB)
        if self._locator_count_loc(tab) > 0:
            tab.first.click()
            self._maybe_wait_for_url("viewSalaryList")
        self._wait_for_page_stable()
        self._raise_if_session_dropped("opening the Salary tab")

    def _wait_for_job_tab_ready(self) -> None:
        """Best-effort wait until the Job tab has finished rendering editable fields.

        OrangeHRM can update the URL before the Job tab content is usable. Waiting for the loading
        spinner to disappear and for at least one dropdown to appear prevents the workflow from
        reading blank values from a half-rendered page.
        """
        self._wait_for_page_stable()
        wait = getattr(self.page, "wait_for_selector", None)
        if callable(wait):
            try:
                wait(self.DROPDOWN_SELECTOR, timeout=self.JOB_DROPDOWN_TIMEOUT_MS)
            except Exception:
                return

    def _wait_for_page_stable(self) -> None:
        """Best-effort wait until OrangeHRM finishes the current in-page load."""
        wait = getattr(self.page, "wait_for_selector", None)
        if callable(wait):
            try:
                wait(self.LOADING_SPINNER, state="detached", timeout=self.SPINNER_TIMEOUT_MS)
            except Exception:
                return

    def _salary_attachment_filename_from_row(self, row: Any) -> str:
        """Extract the filename cell from one OrangeHRM attachment table row.

        Args:
            row: Locator for one attachment table row.

        Returns:
            Normalized filename text, or an empty string when the row has no filename cell.
        """
        cells = row.locator(".oxd-table-cell")
        count = self._locator_count_loc(cells)
        if count == 0:
            return ""
        # OrangeHRM attachment rows start with a checkbox cell; the actual filename is the next
        # cell. Falling back keeps older/fake table layouts working in tests.
        filename_cell_index = 1 if count > 1 else 0
        return self._normalize_table_text(cells.nth(filename_cell_index).text_content() or "")

    def _read_label_scoped_select(self, label_text: str) -> str:
        """Read selected dropdown text near a label.

        Args:
            label_text: Visible label text.

        Returns:
            Selected dropdown text, or an empty string when unavailable.
        """
        select = self._dropdown_trigger_for_label(label_text)
        if select is not None:
            text = (select.text_content() or "").strip()
            if text and text not in ("-- Select --", "--Select--"):
                return text
        return ""

    def _select_dropdown_if_needed(
        self, label_text: str, target_value: str, current_value: str
    ) -> bool:
        """Select a dropdown option when the current value differs.

        Args:
            label_text: Visible label text near the dropdown.
            target_value: Desired option text.
            current_value: Current selected option text.

        Returns:
            ``True`` when an option was selected, otherwise ``False``.
        """
        if current_value == target_value:
            return False
        trigger = self._dropdown_trigger_for_label(label_text)
        if trigger is None:
            self._debug(f"Dropdown trigger not found for label={label_text!r}.")
            return False
        self._debug(
            "Selecting dropdown "
            f"label={label_text!r} current={current_value!r} target={target_value!r}."
        )
        trigger.click()
        if self._click_dropdown_option(target_value):
            self._wait_for_dropdown_value(trigger, target_value)
            return True
        self._debug(f"Dropdown option not found for target={target_value!r}.")
        trigger.click()  # close without selection
        return False

    def _dropdown_trigger_for_label(self, label_text: str) -> Any | None:
        """Return the dropdown trigger nearest to a field label.

        Args:
            label_text: Visible label text.

        Returns:
            Dropdown trigger locator, or ``None`` when unavailable.
        """
        label = self.page.locator("label").filter(has_text=label_text)
        if self._locator_count_loc(label) > 0:
            group = label.first.locator("xpath=ancestor::*[contains(@class, 'oxd-input-group')][1]")
            select = group.locator(self.DROPDOWN_SELECTOR)
            if self._locator_count_loc(select) > 0:
                return select.first
        group = self.page.locator(".oxd-input-group").filter(has_text=label_text)
        if self._locator_count_loc(group) > 0:
            select = group.first.locator(self.DROPDOWN_SELECTOR)
            if self._locator_count_loc(select) > 0:
                return select.first
        return None

    def _input_for_label(self, label_text: str) -> Any | None:
        """Return the input control nearest to a field label.

        Args:
            label_text: Visible label text.

        Returns:
            Input locator, or ``None`` when unavailable.
        """
        label = self.page.locator("label").filter(has_text=label_text)
        if self._locator_count_loc(label) > 0:
            group = label.first.locator("xpath=ancestor::*[contains(@class, 'oxd-input-group')][1]")
            field = group.locator("input")
            if self._locator_count_loc(field) > 0:
                return field.first
        group = self.page.locator(".oxd-input-group").filter(has_text=label_text)
        if self._locator_count_loc(group) > 0:
            field = group.first.locator("input")
            if self._locator_count_loc(field) > 0:
                return field.first
        return None

    def _click_dropdown_option(self, target_value: str) -> bool:
        """Click a visible dropdown option by normalized text.

        Args:
            target_value: Desired option label.

        Returns:
            ``True`` when a matching option was clicked.
        """
        option = self.page.locator(self.DROPDOWN_OPTION).filter(has_text=target_value)
        if self._locator_count_loc(option) > 0:
            option.first.click()
            return True
        options = self.page.locator(self.DROPDOWN_OPTION)
        count = self._locator_count_loc(options)
        visible_options: list[str] = []
        normalized_target = " ".join(target_value.split()).lower()
        for index in range(count):
            candidate = options.nth(index)
            raw_text = candidate.text_content() or ""
            visible_options.append(" ".join(raw_text.split()))
            text = " ".join(raw_text.split()).lower()
            if text == normalized_target:
                candidate.click()
                return True
        self._debug(f"Visible dropdown options for target={target_value!r}: {visible_options!r}.")
        return False

    def _debug(self, message: str) -> None:
        """Print temporary live-debug information when enabled.

        Args:
            message: Diagnostic message.
        """
        if os.environ.get("ORANGEHRM_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}:
            line = f"[orangehrm-debug] {message}"
            print(line)
            debug_path = Path(
                os.environ.get("ORANGEHRM_DEBUG_LOG", "artifacts/orangehrm_debug.log")
            )
            try:
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                with debug_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                return

    def _normalize_table_text(self, value: str) -> str:
        """Normalize table text that OrangeHRM may wrap across visual lines.

        Args:
            value: Raw table cell text.

        Returns:
            Text with all layout whitespace removed.
        """
        return "".join(str(value or "").split())

    def _wait_for_dropdown_value(self, trigger: Any, target_value: str) -> None:
        """Best-effort wait until a dropdown trigger displays the selected value.

        Args:
            trigger: Dropdown trigger locator.
            target_value: Text expected after selection.
        """
        try:
            trigger.wait_for(state="visible", timeout=1000)
        except Exception:
            return
        try:
            self.page.wait_for_timeout(250)
        except Exception:
            return

    def _wait_for_toast_or_stable(self) -> None:
        """Best-effort wait for OrangeHRM success toast."""
        wait = getattr(self.page, "wait_for_selector", None)
        if callable(wait):
            try:
                wait(self.SUCCESS_TOAST, timeout=self.TOAST_TIMEOUT_MS)
            except Exception:
                return

    def _attachments_section(self) -> Any | None:
        """Locate the Attachments section on the Salary tab.

        Returns:
            Locator for the section, or ``None`` when it cannot be found.
        """
        heading = self.page.locator(
            ".oxd-text--h6, .orangehrm-card-container h6, .oxd-table-filter-header-title .oxd-text"
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
