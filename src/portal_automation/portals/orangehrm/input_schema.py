import json
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any


class InputValidationError(ValueError):
    """Raised when OrangeHRM employee input cannot be validated."""


@dataclass(frozen=True)
class SalaryDetails:
    amount: str
    frequency: str
    details: str


@dataclass(frozen=True)
class OrangeHrmEmployeeRecord:
    employee_key: str
    first_name: str
    last_name: str
    job_title: str
    employment_status: str
    salary: SalaryDetails
    employee_id: str | None = None

    @property
    def full_name(self) -> str:
        """Return the display full name for employee search.

        Returns:
            First and last name separated by one space.
        """
        return f"{self.first_name} {self.last_name}"

    @property
    def portal_employee_id(self) -> str:
        """Return the employee id that should be entered into OrangeHRM.

        Returns:
            Portal-facing employee id when configured, otherwise the internal employee key.
        """
        return self.employee_id or self.employee_key


def parse_employee_record(raw: dict[str, Any]) -> OrangeHrmEmployeeRecord:
    """Parse one raw OrangeHRM employee input record.

    Args:
        raw: Raw dictionary loaded from JSON input.

    Returns:
        Validated employee record with stripped string fields.

    Raises:
        InputValidationError: If required fields are missing, blank, or incorrectly typed.
    """
    # Parse and normalize one employee record from the input payload.
    employee_key = _required_string(raw, "employee_key", "record")
    employee_id = _optional_string(raw, "employee_id", "record")
    if employee_id is not None and len(employee_id) > 10:
        raise InputValidationError("record.employee_id: must not exceed 10 characters")
    first_name = _required_string(raw, "first_name", "record")
    last_name = _required_string(raw, "last_name", "record")
    job_title = _required_string(raw, "job_title", "record")
    employment_status = _required_string(raw, "employment_status", "record")
    salary_raw = _required_object(raw, "salary", "record")
    return OrangeHrmEmployeeRecord(
        employee_key=employee_key,
        first_name=first_name,
        last_name=last_name,
        job_title=job_title,
        employment_status=employment_status,
        salary=SalaryDetails(
            amount=_required_string(salary_raw, "amount", "record.salary"),
            frequency=_required_string(salary_raw, "frequency", "record.salary"),
            details=_required_string(salary_raw, "details", "record.salary"),
        ),
        employee_id=employee_id,
    )


def load_employee_records(path: str | Path) -> list[OrangeHrmEmployeeRecord]:
    """Load and validate OrangeHRM employee records from JSON.

    Args:
        path: JSON file path.

    Returns:
        List of validated employee records.

    Raises:
        InputValidationError: If the file cannot be read, JSON is invalid, or records fail schema
            validation.
    """
    input_path = Path(path)
    try:
        parsed = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputValidationError(f"unable to read input file '{input_path}': {exc}") from exc
    except JSONDecodeError as exc:
        raise InputValidationError(f"invalid JSON in '{input_path}': {exc.msg}") from exc

    if not isinstance(parsed, list):
        raise InputValidationError("top-level input must be a list")

    records = []
    # Keep the source index in validation errors so bad rows are easy to find.
    for index, raw_record in enumerate(parsed):
        if not isinstance(raw_record, dict):
            raise InputValidationError(f"record[{index}]: must be an object")
        try:
            records.append(parse_employee_record(raw_record))
        except InputValidationError as exc:
            raise InputValidationError(f"record[{index}]: {exc}") from exc
    return records


def _required_string(raw: dict[str, Any], field_name: str, context: str) -> str:
    """Read a required non-blank string field.

    Args:
        raw: Source dictionary.
        field_name: Required field name.
        context: Human-readable context used in validation errors.

    Returns:
        Stripped string value.

    Raises:
        InputValidationError: If the field is missing, not a string, or blank.
    """
    # Fail fast on missing, non-string, or blank values.
    if field_name not in raw:
        raise InputValidationError(f"{context}: missing field '{field_name}'")
    value = raw[field_name]
    if not isinstance(value, str):
        raise InputValidationError(f"{context}.{field_name}: must be a string")
    stripped = value.strip()
    if not stripped:
        raise InputValidationError(f"{context}.{field_name}: must not be blank")
    return stripped


def _optional_string(raw: dict[str, Any], field_name: str, context: str) -> str | None:
    """Read an optional non-blank string field.

    Args:
        raw: Source dictionary.
        field_name: Optional field name.
        context: Human-readable context used in validation errors.

    Returns:
        Stripped string value or ``None`` when the field is absent.

    Raises:
        InputValidationError: If the field is present but not a non-blank string.
    """
    if field_name not in raw:
        return None
    value = raw[field_name]
    if not isinstance(value, str):
        raise InputValidationError(f"{context}.{field_name}: must be a string")
    stripped = value.strip()
    if not stripped:
        raise InputValidationError(f"{context}.{field_name}: must not be blank")
    return stripped


def _required_object(raw: dict[str, Any], field_name: str, context: str) -> dict[str, Any]:
    """Read a required object field.

    Args:
        raw: Source dictionary.
        field_name: Required field name.
        context: Human-readable context used in validation errors.

    Returns:
        Nested dictionary value.

    Raises:
        InputValidationError: If the field is missing or not a dictionary.
    """
    if field_name not in raw:
        raise InputValidationError(f"{context}: missing field '{field_name}'")
    value = raw[field_name]
    if not isinstance(value, dict):
        raise InputValidationError(f"{context}.{field_name}: must be an object")
    return value
