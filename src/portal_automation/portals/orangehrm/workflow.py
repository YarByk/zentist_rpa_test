from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from portal_automation.core.document_generator import (
    generate_salary_document,
    salary_document_filename,
)
from portal_automation.core.models import ItemResult, ItemStatus, ReasonCode
from portal_automation.core.retries import (
    PortalError,
    execute_with_context_retry,
    is_retryable_error,
)
from portal_automation.portals.orangehrm.input_schema import OrangeHrmEmployeeRecord

OPERATION_NAME = "sync_employee_state"


class FindStatus(str, Enum):  # noqa: UP042
    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    ERROR = "error"


@dataclass(frozen=True)
class FindResult:
    status: FindStatus
    detail: str = ""

    @classmethod
    def found(cls) -> "FindResult":
        """Return a successful employee lookup result.

        Returns:
            ``FindResult`` with status ``FOUND``.
        """
        return cls(FindStatus.FOUND)

    @classmethod
    def not_found(cls) -> "FindResult":
        """Return a not-found employee lookup result.

        Returns:
            ``FindResult`` with status ``NOT_FOUND``.
        """
        return cls(FindStatus.NOT_FOUND)

    @classmethod
    def ambiguous(cls, detail: str = "") -> "FindResult":
        """Return an ambiguous employee lookup result.

        Args:
            detail: Optional human-readable ambiguity detail.

        Returns:
            ``FindResult`` with status ``AMBIGUOUS``.
        """
        return cls(FindStatus.AMBIGUOUS, detail)

    @classmethod
    def error(cls, detail: str = "") -> "FindResult":
        """Return a failed employee lookup result.

        Args:
            detail: Optional human-readable failure detail.

        Returns:
            ``FindResult`` with status ``ERROR``.
        """
        return cls(FindStatus.ERROR, detail)


class OrangeHrmWorkflowPages(Protocol):
    def login(self, username: str, password: str) -> None:
        """Authenticate to OrangeHRM.

        Args:
            username: OrangeHRM username.
            password: OrangeHRM password.

        Raises:
            PortalError: If authentication fails.
        """
        return

    def find_employee_record(self, employee: OrangeHrmEmployeeRecord) -> FindResult:
        """Search for an employee record.

        Args:
            employee: Employee input record.

        Returns:
            Structured lookup result.

        Raises:
            PortalError: If the portal interaction fails before a lookup result can be returned.
        """
        return FindResult.error("workflow interface method was called directly")

    def add_employee(self, employee: OrangeHrmEmployeeRecord) -> None:
        """Create an employee record.

        Args:
            employee: Employee input record.

        Raises:
            PortalError: If creation fails.
        """
        return

    def open_employee_profile(self, employee: OrangeHrmEmployeeRecord) -> None:
        """Open an employee profile after lookup.

        Args:
            employee: Employee input record.

        Raises:
            PortalError: If the profile cannot be opened.
        """
        return

    def update_job(self, employee: OrangeHrmEmployeeRecord) -> None:
        """Write target job values for an employee.

        Args:
            employee: Employee input record.

        Raises:
            PortalError: If the update fails.
        """
        return

    def read_job(self, employee: OrangeHrmEmployeeRecord) -> dict[str, str]:
        """Read current job values for an employee.

        Args:
            employee: Employee input record.

        Returns:
            Dictionary containing current job fields.

        Raises:
            PortalError: If job values cannot be read.
        """
        return {}

    def list_salary_attachments(self, employee: OrangeHrmEmployeeRecord) -> list[str]:
        """List salary attachment filenames for an employee.

        Args:
            employee: Employee input record.

        Returns:
            Attachment filenames visible for the employee.

        Raises:
            PortalError: If attachments cannot be listed.
        """
        return []

    def upload_salary_attachment(self, employee: OrangeHrmEmployeeRecord, path: Path) -> None:
        """Upload a salary document attachment.

        Args:
            employee: Employee input record.
            path: Local document path to upload.

        Raises:
            PortalError: If upload fails.
        """
        return

    def verify_salary_attachment(self, employee: OrangeHrmEmployeeRecord, filename: str) -> bool:
        """Verify that a salary attachment is visible.

        Args:
            employee: Employee input record.
            filename: Expected attachment filename.

        Returns:
            ``True`` when the attachment is visible.

        Raises:
            PortalError: If verification cannot be completed.
        """
        return False


def process_employee(
    employee: OrangeHrmEmployeeRecord,
    pages: OrangeHrmWorkflowPages,
    context: Any,
) -> ItemResult:
    """Synchronize one OrangeHRM employee record.

    Args:
        employee: Employee input record.
        pages: Workflow page adapter.
        context: Runtime context with retry settings, artifact store, and business date.

    Returns:
        Successful item result for the employee.

    Raises:
        PortalError: If lookup, creation, job validation, document generation, or upload fails.
    """
    attempts = 1
    # The employee flow is intentionally split into locate/create, update, and attachment phases.
    created_employee, locate_attempts = _locate_or_create_employee(employee, pages, context)
    attempts = max(attempts, locate_attempts)
    job_updated, job_attempts = _update_job_and_validate(employee, pages, context)
    attempts = max(attempts, job_attempts)
    artifact_path, upload_attempts = _ensure_salary_attachment(employee, pages, context)
    attempts = max(attempts, upload_attempts)
    return ItemResult(
        item_key=employee.employee_key,
        operation=OPERATION_NAME,
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=str(artifact_path) if artifact_path is not None else None,
        attempts=attempts,
        details={
            "created_employee": created_employee,
            "job_updated": job_updated,
            "salary_document_uploaded": artifact_path is not None,
        },
    )


def _locate_or_create_employee(
    employee: OrangeHrmEmployeeRecord,
    pages: OrangeHrmWorkflowPages,
    context: Any,
) -> tuple[bool, int]:
    """Find an employee or create it when missing.

    Args:
        employee: Employee input record.
        pages: Workflow page adapter.
        context: Runtime context used for retries.

    Returns:
        Tuple of ``created_employee`` and max attempts used.

    Raises:
        PortalError: If lookup is ambiguous, lookup fails, creation fails, or the employee is still
            missing after creation.
    """
    attempts = 1
    # Search first so reruns can converge on the same employee instead of creating duplicates.
    first_find, first_find_attempts = execute_with_context_retry(
        context,
        lambda: pages.find_employee_record(employee),
    )
    attempts = max(attempts, first_find_attempts)
    _raise_for_find_failure(first_find)
    if first_find.status is FindStatus.FOUND:
        _, open_attempts = execute_with_context_retry(
            context,
            lambda: pages.open_employee_profile(employee),
        )
        return False, max(attempts, open_attempts)

    try:
        pages.add_employee(employee)
    except PortalError as error:
        if not is_retryable_error(error):
            raise
        attempts = max(attempts, error.attempts)
        # A retryable create failure may still have created the employee server-side, so re-check.
        second_find, second_find_attempts = execute_with_context_retry(
            context,
            lambda: pages.find_employee_record(employee),
        )
        attempts = max(attempts, second_find_attempts)
        _raise_for_find_failure(second_find)
        if second_find.status is FindStatus.NOT_FOUND:
            error.attempts = attempts
            raise
        _, open_attempts = execute_with_context_retry(
            context,
            lambda: pages.open_employee_profile(employee),
        )
        return True, max(attempts, open_attempts)

    # OrangeHRM redirects to the newly created profile after a successful Add Employee save.
    # Staying on that profile is more reliable than immediately returning to Employee List and
    # searching by name, because the public demo can lag its search index and report
    # "No Records Found" even though the profile was just created and is already open.
    return True, attempts


def _raise_for_find_failure(find_result: FindResult) -> None:
    """Raise mapped portal errors for non-terminal lookup failures.

    Args:
        find_result: Employee lookup result.

    Raises:
        PortalError: If the lookup result is ambiguous or errored.
    """
    if find_result.status is FindStatus.AMBIGUOUS:
        detail = find_result.detail or "Employee search returned multiple matches."
        raise PortalError(ReasonCode.EMPLOYEE_MATCH_AMBIGUOUS, detail)
    if find_result.status is FindStatus.ERROR:
        detail = find_result.detail or "Employee search failed."
        raise PortalError(ReasonCode.SEARCH_FAILED, detail)


def _validate_job(employee: OrangeHrmEmployeeRecord, actual: dict[str, str]) -> None:
    """Validate actual job values against the target employee record.

    Args:
        employee: Employee input record with target values.
        actual: Current values read from the portal.

    Raises:
        PortalError: If job title or employment status does not match.
    """
    actual_job_title = actual.get("job_title")
    actual_employment_status = actual.get("employment_status")
    if actual_job_title != employee.job_title:
        raise PortalError(
            ReasonCode.VALIDATION_FAILED,
            f"Job title mismatch for '{employee.full_name}'.",
        )
    if actual_employment_status != employee.employment_status:
        raise PortalError(
            ReasonCode.VALIDATION_FAILED,
            f"Employment status mismatch for '{employee.full_name}'.",
        )


def _job_matches(employee: OrangeHrmEmployeeRecord, actual: dict[str, str]) -> bool:
    """Return whether current job values already match the target.

    Args:
        employee: Employee input record with target values.
        actual: Current values read from the portal.

    Returns:
        ``True`` when job title and employment status both match.
    """
    return (
        actual.get("job_title") == employee.job_title
        and actual.get("employment_status") == employee.employment_status
    )


def _update_job_and_validate(
    employee: OrangeHrmEmployeeRecord,
    pages: OrangeHrmWorkflowPages,
    context: Any,
) -> tuple[bool, int]:
    """Update job values when needed and validate the final state.

    Args:
        employee: Employee input record.
        pages: Workflow page adapter.
        context: Runtime context used for retries.

    Returns:
        Tuple of ``job_updated`` and max attempts used.

    Raises:
        PortalError: If update or final validation fails.
    """
    attempts = 1
    # Read-before-write keeps reruns idempotent when the target state is already correct.
    actual, read_attempts = execute_with_context_retry(
        context,
        lambda: pages.read_job(employee),
    )
    attempts = max(attempts, read_attempts)
    if _job_matches(employee, actual):
        return False, attempts

    try:
        pages.update_job(employee)
    except PortalError as error:
        if not is_retryable_error(error):
            raise
        attempts = max(attempts, error.attempts)
        actual, read_attempts = execute_with_context_retry(
            context,
            lambda: pages.read_job(employee),
        )
        attempts = max(attempts, read_attempts)
        try:
            _validate_job(employee, actual)
        except PortalError:
            error.attempts = attempts
            raise error from None
        return True, attempts

    actual, read_attempts = execute_with_context_retry(
        context,
        lambda: pages.read_job(employee),
    )
    attempts = max(attempts, read_attempts)
    _validate_job(employee, actual)
    return True, attempts


def _ensure_salary_attachment(
    employee: OrangeHrmEmployeeRecord,
    pages: OrangeHrmWorkflowPages,
    context: Any,
) -> tuple[Path | None, int]:
    """Ensure the expected salary document attachment exists.

    Args:
        employee: Employee input record.
        pages: Workflow page adapter.
        context: Runtime context with artifact store and business date.

    Returns:
        Tuple of uploaded document path, or ``None`` when already present, and max attempts used.

    Raises:
        PortalError: If document generation, upload, or verification fails.
        OSError: If the generated salary document cannot be written.
    """
    attempts = 1
    filename = salary_document_filename(employee.employee_key, context.business_date)
    # Skip upload when the expected attachment is already visible for this employee/date.
    attachments, list_attempts = execute_with_context_retry(
        context,
        lambda: pages.list_salary_attachments(employee),
    )
    attempts = max(attempts, list_attempts)
    if filename in attachments:
        return None, attempts

    content = generate_salary_document(
        employee_name=employee.full_name,
        employee_key=employee.employee_key,
        job_title=employee.job_title,
        employment_status=employee.employment_status,
        salary_amount=employee.salary.amount,
        pay_frequency=employee.salary.frequency,
        details=employee.salary.details,
        business_date=context.business_date,
        run_id=context.run_id,
    )
    if not content:
        raise PortalError(
            ReasonCode.DOCUMENT_GENERATION_FAILED,
            f"Salary document generation failed for '{employee.full_name}'.",
        )

    doc_path = context.artifacts.salary_document_path(
        context.run_id,
        employee.employee_key,
        context.business_date,
    )
    path = context.artifacts.write_text(doc_path, content)
    try:
        pages.upload_salary_attachment(employee, path)
    except PortalError as error:
        if not is_retryable_error(error):
            raise
        attempts = max(attempts, error.attempts)
        uploaded, verify_attempts = execute_with_context_retry(
            context,
            lambda: pages.verify_salary_attachment(employee, filename),
        )
        attempts = max(attempts, verify_attempts)
        if uploaded:
            return path, attempts
        error.attempts = attempts
        raise

    uploaded, verify_attempts = execute_with_context_retry(
        context,
        lambda: pages.verify_salary_attachment(employee, filename),
    )
    attempts = max(attempts, verify_attempts)
    if not uploaded:
        raise PortalError(
            ReasonCode.UPLOAD_FAILED,
            f"Salary attachment verification failed for '{employee.full_name}'.",
        )
    return path, attempts
