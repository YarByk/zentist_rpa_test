import re
from datetime import date

from portal_automation.core.artifact_store import _sanitize_key

_DEMO_SECRET_VALUES = ("secret_" + "sauce", "admin" + "123")
_SECRET_ASSIGNMENT_RE = re.compile(r"(?i)\b(password|secret|token|credential)\s*[:=]\s*[^\s,;]+")


def salary_document_filename(employee_key: str, business_date: date) -> str:
    return f"salary_{_sanitize_key(employee_key)}_{business_date.isoformat()}.txt"


def generate_salary_document(
    *,
    employee_name: str,
    employee_key: str,
    job_title: str,
    employment_status: str,
    salary_amount: str,
    pay_frequency: str,
    details: str,
    business_date: date,
    run_id: str | None = None,
) -> str:
    run_line = f"Run ID: {_sanitize_text(run_id)}\n" if run_id else ""
    return (
        f"Employee: {_sanitize_text(employee_name)}\n"
        f"Employee key: {_sanitize_text(employee_key)}\n"
        f"Job title: {_sanitize_text(job_title)}\n"
        f"Employment status: {_sanitize_text(employment_status)}\n"
        f"Salary amount: {_sanitize_text(salary_amount)}\n"
        f"Pay frequency: {_sanitize_text(pay_frequency)}\n"
        f"Details: {_sanitize_text(details)}\n"
        f"Business date: {business_date.isoformat()}\n"
        f"{run_line}"
    )


def _sanitize_text(value: str | None) -> str:
    text = "" if value is None else str(value)
    for secret_value in _DEMO_SECRET_VALUES:
        text = text.replace(secret_value, "[REDACTED]")
    return _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
