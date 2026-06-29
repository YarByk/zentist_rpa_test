from datetime import date

from portal_automation.core.artifact_store import _sanitize_key


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
) -> str:
    return (
        f"Employee: {employee_name}\n"
        f"Employee key: {employee_key}\n"
        f"Job title: {job_title}\n"
        f"Employment status: {employment_status}\n"
        f"Salary amount: {salary_amount}\n"
        f"Pay frequency: {pay_frequency}\n"
        f"Details: {details}\n"
        f"Business date: {business_date.isoformat()}\n"
    )
