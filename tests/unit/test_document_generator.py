from datetime import date
from pathlib import Path

from portal_automation.core.document_generator import (
    generate_salary_document,
    salary_document_filename,
)

ROOT = Path(__file__).resolve().parents[2]


def salary_document() -> str:
    return generate_salary_document(
        employee_name="Alice Johnson",
        employee_key="emp-001",
        job_title="QA Engineer",
        employment_status="Full-Time Permanent",
        salary_amount="90000 USD",
        pay_frequency="Annual",
        details="Base salary for 2026",
        business_date=date(2026, 6, 29),
    )


def test_salary_document_filename_uses_expected_normal_key_format() -> None:
    assert salary_document_filename("emp-001", date(2026, 6, 29)) == (
        "salary_emp-001_2026-06-29.txt"
    )


def test_salary_document_filename_sanitizes_unsafe_key() -> None:
    assert salary_document_filename(" emp/00:1 ", date(2026, 6, 29)) == (
        "salary_emp_00_1_2026-06-29.txt"
    )


def test_generate_salary_document_uses_required_field_order() -> None:
    assert salary_document() == (
        "Employee: Alice Johnson\n"
        "Employee key: emp-001\n"
        "Job title: QA Engineer\n"
        "Employment status: Full-Time Permanent\n"
        "Salary amount: 90000 USD\n"
        "Pay frequency: Annual\n"
        "Details: Base salary for 2026\n"
        "Business date: 2026-06-29\n"
    )


def test_generate_salary_document_is_deterministic_for_same_input() -> None:
    assert salary_document() == salary_document()


def test_generate_salary_document_includes_run_id_when_supplied() -> None:
    document = generate_salary_document(
        employee_name="Alice Johnson",
        employee_key="emp-001",
        job_title="QA Engineer",
        employment_status="Full-Time Permanent",
        salary_amount="90000 USD",
        pay_frequency="Annual",
        details="Base salary for 2026",
        business_date=date(2026, 6, 29),
        run_id="run-1",
    )

    assert "Run ID: run-1\n" in document


def test_generate_salary_document_redacts_secret_like_input_values() -> None:
    document = generate_salary_document(
        employee_name="Alice secret_sauce",
        employee_key="emp-001",
        job_title="QA Engineer",
        employment_status="Full-Time Permanent",
        salary_amount="90000 USD",
        pay_frequency="Annual",
        details="password=hunter2 token:abc admin123 credential=id-9",
        business_date=date(2026, 6, 29),
        run_id="run-secret_sauce",
    )

    assert "secret_sauce" not in document
    assert "admin123" not in document
    assert "hunter2" not in document
    assert "token:abc" not in document
    assert "credential=id-9" not in document
    assert "[REDACTED]" in document


def test_generated_content_ends_with_exactly_one_trailing_newline() -> None:
    document = salary_document()

    assert document.endswith("\n")
    assert not document.endswith("\n\n")


def test_generated_content_does_not_include_secret_like_values_when_not_inputs() -> None:
    document = salary_document()

    assert "secret_sauce" not in document
    assert "admin123" not in document
    assert "password" not in document.lower()


def test_document_generator_does_not_import_from_orangehrm_portal_modules() -> None:
    source = (ROOT / "src/portal_automation/core/document_generator.py").read_text(encoding="utf-8")

    assert "portal_automation.portals.orangehrm" not in source


def test_forbidden_modules_were_not_created() -> None:
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
