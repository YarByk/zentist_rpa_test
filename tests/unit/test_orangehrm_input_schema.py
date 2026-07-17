import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.orangehrm.input_schema import (
    InputValidationError,
    OrangeHrmEmployeeRecord,
    load_employee_records,
    parse_employee_record,
)
from portal_automation.portals.orangehrm.runner import OrangeHrmRunner

ROOT = Path(__file__).resolve().parents[2]


def valid_record() -> dict:
    # Raw fixture intentionally includes whitespace so parser normalization is tested too.
    """Valid record.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    return {
        "employee_key": " emp-alice-johnson ",
        "first_name": " Alice ",
        "last_name": " Johnson ",
        "job_title": " QA Engineer ",
        "employment_status": " Full-Time Permanent ",
        "salary": {
            "amount": " 90000 USD ",
            "frequency": " Annual ",
            "details": " Base salary for 2026 ",
        },
    }


def write_json(path: Path, value) -> Path:
    # Small helper for building temporary input files with production-like JSON shape.
    """Write json.

    Args:
        path: Value supplied by the test or fixture for `path`.
        value: Value supplied by the test or fixture for `value`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_valid_record_parses_into_employee_record() -> None:
    """Verify that valid record parses into employee record.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    record = parse_employee_record(valid_record())

    assert isinstance(record, OrangeHrmEmployeeRecord)
    assert record.employee_key == "emp-alice-johnson"
    assert record.employee_id is None
    assert record.portal_employee_id == "emp-alice-johnson"
    assert record.salary.amount == "90000 USD"


def test_optional_employee_id_parses_as_portal_employee_id() -> None:
    """Verify that optional employee_id is used as the OrangeHRM-facing id."""
    raw = valid_record()
    raw["employee_id"] = " alice001 "

    record = parse_employee_record(raw)

    assert record.employee_key == "emp-alice-johnson"
    assert record.employee_id == "alice001"
    assert record.portal_employee_id == "alice001"


def test_employee_id_longer_than_orangehrm_limit_fails_validation() -> None:
    """Verify that portal-facing employee_id is limited before Playwright runs."""
    raw = valid_record()
    raw["employee_id"] = "emp-alice-johnson"

    with pytest.raises(InputValidationError, match="employee_id.*10 characters"):
        parse_employee_record(raw)


def test_parsed_values_are_stripped_strings() -> None:
    """Verify that parsed values are stripped strings.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    record = parse_employee_record(valid_record())

    assert record.first_name == "Alice"
    assert record.last_name == "Johnson"
    assert record.salary.frequency == "Annual"


def test_full_name_returns_first_and_last_name() -> None:
    """Verify that full name returns first and last name.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    record = parse_employee_record(valid_record())

    assert record.full_name == "Alice Johnson"


@pytest.mark.parametrize("field_name", ["employee_key", "first_name"])
def test_missing_required_employee_field_fails_validation(field_name) -> None:
    """Verify that missing required employee field fails validation.

    Args:
        field_name: Value supplied by the test or fixture for `field_name`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    raw = valid_record()
    raw.pop(field_name)

    with pytest.raises(InputValidationError, match=field_name):
        parse_employee_record(raw)


def test_missing_salary_fails_validation() -> None:
    """Verify that missing salary fails validation.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    raw = valid_record()
    raw.pop("salary")

    with pytest.raises(InputValidationError, match="salary"):
        parse_employee_record(raw)


def test_missing_salary_field_fails_validation() -> None:
    """Verify that missing salary field fails validation.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    raw = valid_record()
    raw["salary"].pop("amount")

    with pytest.raises(InputValidationError, match="amount"):
        parse_employee_record(raw)


def test_blank_required_string_fails_validation() -> None:
    """Verify that blank required string fails validation.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    raw = valid_record()
    raw["job_title"] = "   "

    with pytest.raises(InputValidationError, match="job_title"):
        parse_employee_record(raw)


def test_top_level_non_list_json_fails_validation(tmp_path) -> None:
    """Verify that top level non list json fails validation.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = write_json(tmp_path / "employees.json", {"employee_key": "emp-001"})

    with pytest.raises(InputValidationError, match="top-level input must be a list"):
        load_employee_records(path)


def test_non_object_record_fails_validation(tmp_path) -> None:
    """Verify that non object record fails validation.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = write_json(tmp_path / "employees.json", ["not-object"])

    with pytest.raises(InputValidationError, match=r"record\[0\].*object"):
        load_employee_records(path)


def test_invalid_json_fails_validation(tmp_path) -> None:
    """Verify that invalid json fails validation.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = tmp_path / "employees.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(InputValidationError, match="invalid JSON"):
        load_employee_records(path)


def test_unreadable_input_file_fails_validation(tmp_path) -> None:
    """Verify that unreadable input file fails validation.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = tmp_path / "missing.json"

    with pytest.raises(InputValidationError, match="unable to read input file"):
        load_employee_records(path)


def test_all_sample_records_are_valid() -> None:
    """Verify that all sample records are valid.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    records = load_employee_records(ROOT / "data/orangehrm_employees.json")

    assert all(isinstance(record, OrangeHrmEmployeeRecord) for record in records)


def test_sample_data_contains_expected_people() -> None:
    """Verify that sample data contains expected people.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    records = load_employee_records(ROOT / "data/orangehrm_employees.json")

    assert {record.full_name for record in records} == {
        "Alice Johnson",
        "Bob Smith",
        "Zara Novak",
    }


def test_sample_data_employee_ids_fit_orangehrm_limit() -> None:
    """Verify that sample OrangeHRM ids fit the portal's 10-character limit."""
    records = load_employee_records(ROOT / "data/orangehrm_employees.json")

    assert {record.portal_employee_id for record in records} == {
        "alice001",
        "bob001",
        "zara001",
    }
    assert all(len(record.portal_employee_id) <= 10 for record in records)


def test_sample_data_contains_exactly_three_records() -> None:
    """Verify that sample data contains exactly three records.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    records = load_employee_records(ROOT / "data/orangehrm_employees.json")

    assert len(records) == 3


def test_sample_data_does_not_contain_existence_path_control_flags() -> None:
    """Verify that sample data does not contain existence path control flags.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    raw_records = json.loads((ROOT / "data/orangehrm_employees.json").read_text(encoding="utf-8"))

    for raw_record in raw_records:
        assert "exists" not in raw_record
        assert "is_new" not in raw_record
        assert "path" not in raw_record


@dataclass
class ConfigStub:
    # Runner.load_items only needs the configured input path.
    orangehrm_input_path: str


@dataclass
class ContextStub:
    # Minimal context wrapper matching the runner's load_items signature.
    config: ConfigStub


def test_orangehrm_runner_load_items_reads_config_input_path(tmp_path) -> None:
    """Verify that orangehrm runner load items reads config input path.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = write_json(tmp_path / "employees.json", [valid_record()])
    context = ContextStub(config=ConfigStub(orangehrm_input_path=str(path)))

    items = OrangeHrmRunner().load_items(context)

    assert len(items) == 1
    assert items[0].full_name == "Alice Johnson"


def test_invalid_input_maps_to_input_validation_failed_portal_error(tmp_path) -> None:
    # Runner boundary should translate schema errors into PortalError reason codes.
    """Verify that invalid input maps to input validation failed portal error.

    Args:
        tmp_path: Value supplied by the test or fixture for `tmp_path`.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    path = write_json(tmp_path / "employees.json", [{"first_name": "Alice"}])
    context = ContextStub(config=ConfigStub(orangehrm_input_path=str(path)))

    with pytest.raises(PortalError) as error:
        OrangeHrmRunner().load_items(context)

    assert error.value.reason is ReasonCode.INPUT_VALIDATION_FAILED
    assert "employee_key" in error.value.detail


def test_schema_and_runner_do_not_import_playwright_browser_or_page_modules() -> None:
    """Verify that schema and runner do not import playwright browser or page modules.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    schema_source = (ROOT / "src/portal_automation/portals/orangehrm/input_schema.py").read_text(
        encoding="utf-8"
    )
    runner_source = (ROOT / "src/portal_automation/portals/orangehrm/runner.py").read_text(
        encoding="utf-8"
    )

    assert "playwright" not in schema_source.lower()
    assert "browser" not in schema_source.lower()
    assert "page" not in schema_source.lower()
    assert "import playwright" not in runner_source.lower()
    assert "from playwright" not in runner_source.lower()


def test_schema_source_does_not_import_persistence_or_sqlite_modules() -> None:
    """Verify that schema source does not import persistence or sqlite modules.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    source = (ROOT / "src/portal_automation/portals/orangehrm/input_schema.py").read_text(
        encoding="utf-8"
    )

    assert "persistence" not in source
    assert "sqlite" not in source


def test_source_and_sample_data_do_not_contain_demo_credentials() -> None:
    """Verify that source and sample data do not contain demo credentials.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    paths = [
        ROOT / "src/portal_automation/portals/orangehrm/input_schema.py",
        ROOT / "src/portal_automation/portals/orangehrm/runner.py",
        ROOT / "data/orangehrm_employees.json",
    ]

    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert "secret_sauce" not in content
        assert "admin123" not in content


def test_forbidden_modules_were_not_created() -> None:
    """Verify that forbidden modules were not created.

    Returns:
        None. The test communicates success through assertions.

    Raises:
        AssertionError: If the behavior under test does not match the expected outcome.
    """
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
