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
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_valid_record_parses_into_employee_record() -> None:
    record = parse_employee_record(valid_record())

    assert isinstance(record, OrangeHrmEmployeeRecord)
    assert record.employee_key == "emp-alice-johnson"
    assert record.salary.amount == "90000 USD"


def test_parsed_values_are_stripped_strings() -> None:
    record = parse_employee_record(valid_record())

    assert record.first_name == "Alice"
    assert record.last_name == "Johnson"
    assert record.salary.frequency == "Annual"


def test_full_name_returns_first_and_last_name() -> None:
    record = parse_employee_record(valid_record())

    assert record.full_name == "Alice Johnson"


@pytest.mark.parametrize("field_name", ["employee_key", "first_name"])
def test_missing_required_employee_field_fails_validation(field_name) -> None:
    raw = valid_record()
    raw.pop(field_name)

    with pytest.raises(InputValidationError, match=field_name):
        parse_employee_record(raw)


def test_missing_salary_fails_validation() -> None:
    raw = valid_record()
    raw.pop("salary")

    with pytest.raises(InputValidationError, match="salary"):
        parse_employee_record(raw)


def test_missing_salary_field_fails_validation() -> None:
    raw = valid_record()
    raw["salary"].pop("amount")

    with pytest.raises(InputValidationError, match="amount"):
        parse_employee_record(raw)


def test_blank_required_string_fails_validation() -> None:
    raw = valid_record()
    raw["job_title"] = "   "

    with pytest.raises(InputValidationError, match="job_title"):
        parse_employee_record(raw)


def test_top_level_non_list_json_fails_validation(tmp_path) -> None:
    path = write_json(tmp_path / "employees.json", {"employee_key": "emp-001"})

    with pytest.raises(InputValidationError, match="top-level input must be a list"):
        load_employee_records(path)


def test_non_object_record_fails_validation(tmp_path) -> None:
    path = write_json(tmp_path / "employees.json", ["not-object"])

    with pytest.raises(InputValidationError, match=r"record\[0\].*object"):
        load_employee_records(path)


def test_invalid_json_fails_validation(tmp_path) -> None:
    path = tmp_path / "employees.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(InputValidationError, match="invalid JSON"):
        load_employee_records(path)


def test_unreadable_input_file_fails_validation(tmp_path) -> None:
    path = tmp_path / "missing.json"

    with pytest.raises(InputValidationError, match="unable to read input file"):
        load_employee_records(path)


def test_all_sample_records_are_valid() -> None:
    records = load_employee_records(ROOT / "data/orangehrm_employees.json")

    assert all(isinstance(record, OrangeHrmEmployeeRecord) for record in records)


def test_sample_data_contains_expected_people() -> None:
    records = load_employee_records(ROOT / "data/orangehrm_employees.json")

    assert {record.full_name for record in records} == {
        "Alice Johnson",
        "Bob Smith",
        "Zara Novak",
    }


def test_sample_data_contains_exactly_three_records() -> None:
    records = load_employee_records(ROOT / "data/orangehrm_employees.json")

    assert len(records) == 3


def test_sample_data_does_not_contain_existence_path_control_flags() -> None:
    raw_records = json.loads((ROOT / "data/orangehrm_employees.json").read_text(encoding="utf-8"))

    for raw_record in raw_records:
        assert "exists" not in raw_record
        assert "is_new" not in raw_record
        assert "path" not in raw_record


@dataclass
class ConfigStub:
    orangehrm_input_path: str


@dataclass
class ContextStub:
    config: ConfigStub


def test_orangehrm_runner_load_items_reads_config_input_path(tmp_path) -> None:
    path = write_json(tmp_path / "employees.json", [valid_record()])
    context = ContextStub(config=ConfigStub(orangehrm_input_path=str(path)))

    items = OrangeHrmRunner().load_items(context)

    assert len(items) == 1
    assert items[0].full_name == "Alice Johnson"


def test_invalid_input_maps_to_input_validation_failed_portal_error(tmp_path) -> None:
    path = write_json(tmp_path / "employees.json", [{"first_name": "Alice"}])
    context = ContextStub(config=ConfigStub(orangehrm_input_path=str(path)))

    with pytest.raises(PortalError) as error:
        OrangeHrmRunner().load_items(context)

    assert error.value.reason is ReasonCode.INPUT_VALIDATION_FAILED
    assert "employee_key" in error.value.detail


def test_schema_and_runner_do_not_import_playwright_browser_or_page_modules() -> None:
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
    source = (ROOT / "src/portal_automation/portals/orangehrm/input_schema.py").read_text(
        encoding="utf-8"
    )

    assert "persistence" not in source
    assert "sqlite" not in source


def test_source_and_sample_data_do_not_contain_demo_credentials() -> None:
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
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
