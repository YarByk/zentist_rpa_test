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

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


def parse_employee_record(raw: dict[str, Any]) -> OrangeHrmEmployeeRecord:
    employee_key = _required_string(raw, "employee_key", "record")
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
    )


def load_employee_records(path: str | Path) -> list[OrangeHrmEmployeeRecord]:
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
    for index, raw_record in enumerate(parsed):
        if not isinstance(raw_record, dict):
            raise InputValidationError(f"record[{index}]: must be an object")
        try:
            records.append(parse_employee_record(raw_record))
        except InputValidationError as exc:
            raise InputValidationError(f"record[{index}]: {exc}") from exc
    return records


def _required_string(raw: dict[str, Any], field_name: str, context: str) -> str:
    if field_name not in raw:
        raise InputValidationError(f"{context}: missing field '{field_name}'")
    value = raw[field_name]
    if not isinstance(value, str):
        raise InputValidationError(f"{context}.{field_name}: must be a string")
    stripped = value.strip()
    if not stripped:
        raise InputValidationError(f"{context}.{field_name}: must not be blank")
    return stripped


def _required_object(raw: dict[str, Any], field_name: str, context: str) -> dict[str, Any]:
    if field_name not in raw:
        raise InputValidationError(f"{context}: missing field '{field_name}'")
    value = raw[field_name]
    if not isinstance(value, dict):
        raise InputValidationError(f"{context}.{field_name}: must be an object")
    return value
