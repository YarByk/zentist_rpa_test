from pathlib import Path
from typing import Any

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.orangehrm.input_schema import OrangeHrmEmployeeRecord
from portal_automation.portals.orangehrm.workflow import FindResult


class OrangeHrmPages:
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

    def login(self) -> None:
        password = getattr(self.config, "orangehrm_password", None)
        if not isinstance(password, str) or not password.strip():
            raise PortalError(
                ReasonCode.CREDENTIAL_EXPIRED,
                "OrangeHRM password is not configured.",
            )

        self.page.goto(self.config.orangehrm_base_url)
        self.page.get_by_label(self.USERNAME_LABEL).fill(self.config.orangehrm_username)
        self.page.get_by_label(self.PASSWORD_LABEL).fill(password.strip())
        self.page.get_by_role("button", name="Login").click()
        if getattr(self.page, "login_succeeded", True) is False:
            raise PortalError(ReasonCode.LOGIN_FAILED, "OrangeHRM login failed.")

    def find_employee_record(self, employee: OrangeHrmEmployeeRecord) -> FindResult:
        self.page.get_by_label(self.EMPLOYEE_SEARCH_LABEL).fill(employee.full_name)
        self.page.get_by_role("button", name="Search").click()
        if getattr(self.page, "employee_search_error", False):
            return FindResult.error("Employee search failed.")

        if hasattr(self.page, "employee_search_results"):
            results = list(self.page.employee_search_results)
            if len(results) == 0:
                return FindResult.not_found()
            if len(results) == 1:
                return FindResult.found()
            return FindResult.ambiguous("Employee search returned multiple matches.")

        return FindResult.error("Employee search result state is unavailable.")

    def add_employee(self, employee: OrangeHrmEmployeeRecord) -> None:
        self.page.get_by_role("button", name="Add").click()
        self.page.get_by_label(self.FIRST_NAME_LABEL).fill(employee.first_name)
        self.page.get_by_label(self.LAST_NAME_LABEL).fill(employee.last_name)
        self.page.get_by_label(self.EMPLOYEE_ID_LABEL).fill(employee.employee_key)
        self.page.get_by_role("button", name="Save").click()

    def open_employee_profile(self, employee: OrangeHrmEmployeeRecord) -> None:
        self.page.get_by_role("link", name=employee.full_name).click()

    def update_job(self, employee: OrangeHrmEmployeeRecord) -> None:
        self.page.get_by_role("tab", name="Job").click()
        self.page.get_by_label(self.JOB_TITLE_LABEL).fill(employee.job_title)
        self.page.get_by_label(self.EMPLOYMENT_STATUS_LABEL).fill(employee.employment_status)
        self.page.get_by_role("button", name="Save").click()

    def read_job(self, employee: OrangeHrmEmployeeRecord) -> dict[str, str]:
        if hasattr(self.page, "job_values"):
            return dict(self.page.job_values)
        return {
            "job_title": self.page.get_by_label(self.JOB_TITLE_LABEL).text_content(),
            "employment_status": self.page.get_by_label(
                self.EMPLOYMENT_STATUS_LABEL
            ).text_content(),
        }

    def list_salary_attachments(self, employee: OrangeHrmEmployeeRecord) -> list[str]:
        if hasattr(self.page, "attachment_filenames"):
            return list(self.page.attachment_filenames)
        text = self.page.locator("[data-test='salary-attachments']").text_content() or ""
        return [line.strip() for line in text.splitlines() if line.strip()]

    def upload_salary_attachment(self, employee: OrangeHrmEmployeeRecord, path: Path) -> None:
        self.page.get_by_label(self.SALARY_ATTACHMENT_LABEL).set_input_files(str(path))
        self.page.get_by_role("button", name="Upload").click()

    def verify_salary_attachment(self, employee: OrangeHrmEmployeeRecord, filename: str) -> bool:
        return filename in self.list_salary_attachments(employee)
