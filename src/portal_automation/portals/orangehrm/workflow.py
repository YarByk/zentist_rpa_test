from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from portal_automation.core.document_generator import (
    generate_salary_document,
    salary_document_filename,
)
from portal_automation.core.models import ItemResult, ItemStatus, ReasonCode
from portal_automation.core.retries import PortalError
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
        return cls(FindStatus.FOUND)

    @classmethod
    def not_found(cls) -> "FindResult":
        return cls(FindStatus.NOT_FOUND)

    @classmethod
    def ambiguous(cls, detail: str = "") -> "FindResult":
        return cls(FindStatus.AMBIGUOUS, detail)

    @classmethod
    def error(cls, detail: str = "") -> "FindResult":
        return cls(FindStatus.ERROR, detail)


class OrangeHrmWorkflowPages(Protocol):
    def find_employee_record(self, employee: OrangeHrmEmployeeRecord) -> FindResult:
        return FindResult.error("workflow interface method was called directly")

    def add_employee(self, employee: OrangeHrmEmployeeRecord) -> None:
        return

    def open_employee_profile(self, employee: OrangeHrmEmployeeRecord) -> None:
        return

    def update_job(self, employee: OrangeHrmEmployeeRecord) -> None:
        return

    def read_job(self, employee: OrangeHrmEmployeeRecord) -> dict[str, str]:
        return {}

    def list_salary_attachments(self, employee: OrangeHrmEmployeeRecord) -> list[str]:
        return []

    def upload_salary_attachment(self, employee: OrangeHrmEmployeeRecord, path: Path) -> None:
        return

    def verify_salary_attachment(self, employee: OrangeHrmEmployeeRecord, filename: str) -> bool:
        return False


def process_employee(
    employee: OrangeHrmEmployeeRecord,
    pages: OrangeHrmWorkflowPages,
    context: Any,
) -> ItemResult:
    created_employee = _locate_or_create_employee(employee, pages)
    pages.update_job(employee)
    _validate_job(employee, pages.read_job(employee))
    artifact_path = _ensure_salary_attachment(employee, pages, context)
    return ItemResult(
        item_key=employee.employee_key,
        operation=OPERATION_NAME,
        status=ItemStatus.SUCCESS,
        reason_code=None,
        error_detail=None,
        artifact_path=str(artifact_path) if artifact_path is not None else None,
        attempts=1,
        details={
            "created_employee": created_employee,
            "salary_document_uploaded": artifact_path is not None,
        },
    )


def _locate_or_create_employee(
    employee: OrangeHrmEmployeeRecord,
    pages: OrangeHrmWorkflowPages,
) -> bool:
    first_find = pages.find_employee_record(employee)
    _raise_for_find_failure(first_find)
    if first_find.status is FindStatus.FOUND:
        pages.open_employee_profile(employee)
        return False

    pages.add_employee(employee)
    second_find = pages.find_employee_record(employee)
    _raise_for_find_failure(second_find)
    if second_find.status is FindStatus.NOT_FOUND:
        raise PortalError(
            ReasonCode.EMPLOYEE_NOT_FOUND,
            f"Employee '{employee.full_name}' was not found after creation.",
        )
    pages.open_employee_profile(employee)
    return True


def _raise_for_find_failure(find_result: FindResult) -> None:
    if find_result.status is FindStatus.AMBIGUOUS:
        detail = find_result.detail or "Employee search returned multiple matches."
        raise PortalError(ReasonCode.EMPLOYEE_MATCH_AMBIGUOUS, detail)
    if find_result.status is FindStatus.ERROR:
        detail = find_result.detail or "Employee search failed."
        raise PortalError(ReasonCode.SEARCH_FAILED, detail)


def _validate_job(employee: OrangeHrmEmployeeRecord, actual: dict[str, str]) -> None:
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


def _ensure_salary_attachment(
    employee: OrangeHrmEmployeeRecord,
    pages: OrangeHrmWorkflowPages,
    context: Any,
) -> Path | None:
    filename = salary_document_filename(employee.employee_key, context.business_date)
    if filename in pages.list_salary_attachments(employee):
        return None

    content = generate_salary_document(
        employee_name=employee.full_name,
        employee_key=employee.employee_key,
        job_title=employee.job_title,
        employment_status=employee.employment_status,
        salary_amount=employee.salary.amount,
        pay_frequency=employee.salary.frequency,
        details=employee.salary.details,
        business_date=context.business_date,
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
    pages.upload_salary_attachment(employee, path)
    if not pages.verify_salary_attachment(employee, filename):
        raise PortalError(
            ReasonCode.UPLOAD_FAILED,
            f"Salary attachment verification failed for '{employee.full_name}'.",
        )
    return path
