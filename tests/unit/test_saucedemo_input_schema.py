import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from portal_automation.core.models import ReasonCode
from portal_automation.core.retries import PortalError
from portal_automation.portals.saucedemo.input_schema import (
    CheckoutProfile,
    InputValidationError,
    SauceDemoAccount,
    load_account_records,
    parse_account_record,
)
from portal_automation.portals.saucedemo.runner import SauceDemoRunner

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_USERNAMES = {
    "standard_user",
    "locked_out_user",
    "problem_user",
    "performance_glitch_user",
    "error_user",
    "visual_user",
}


def valid_record() -> dict:
    return {
        "account_key": " standard_user ",
        "username": " standard_user ",
        "items_to_add": 3,
        "checkout_profile": {
            "first_name": " Standard ",
            "last_name": " User ",
            "postal_code": " 10001 ",
        },
    }


def write_json(path: Path, value) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_valid_record_parses_into_sauce_demo_account() -> None:
    account = parse_account_record(valid_record())

    assert isinstance(account, SauceDemoAccount)
    assert isinstance(account.checkout_profile, CheckoutProfile)
    assert account.username == "standard_user"


def test_parsed_string_values_are_stripped() -> None:
    account = parse_account_record(valid_record())

    assert account.account_key == "standard_user"
    assert account.checkout_profile.first_name == "Standard"
    assert account.checkout_profile.postal_code == "10001"


def test_items_to_add_defaults_to_three() -> None:
    raw = valid_record()
    raw.pop("items_to_add")

    assert parse_account_record(raw).items_to_add == 3


@pytest.mark.parametrize("field_name", ["account_key", "username"])
def test_missing_required_account_field_fails_validation(field_name) -> None:
    raw = valid_record()
    raw.pop(field_name)

    with pytest.raises(InputValidationError, match=field_name):
        parse_account_record(raw)


def test_missing_checkout_profile_fails_validation() -> None:
    raw = valid_record()
    raw.pop("checkout_profile")

    with pytest.raises(InputValidationError, match="checkout_profile"):
        parse_account_record(raw)


def test_missing_checkout_profile_field_fails_validation() -> None:
    raw = valid_record()
    raw["checkout_profile"].pop("postal_code")

    with pytest.raises(InputValidationError, match="postal_code"):
        parse_account_record(raw)


def test_blank_required_string_fails_validation() -> None:
    raw = valid_record()
    raw["checkout_profile"]["first_name"] = "   "

    with pytest.raises(InputValidationError, match="first_name"):
        parse_account_record(raw)


@pytest.mark.parametrize("value", [0, -1, True, "3"])
def test_invalid_items_to_add_fails_validation(value) -> None:
    raw = valid_record()
    raw["items_to_add"] = value

    with pytest.raises(InputValidationError, match="items_to_add"):
        parse_account_record(raw)


def test_top_level_non_list_json_fails_validation(tmp_path) -> None:
    path = write_json(tmp_path / "accounts.json", {"account_key": "standard_user"})

    with pytest.raises(InputValidationError, match="top-level input must be a list"):
        load_account_records(path)


def test_non_object_record_fails_validation(tmp_path) -> None:
    path = write_json(tmp_path / "accounts.json", ["not-object"])

    with pytest.raises(InputValidationError, match=r"record\[0\].*object"):
        load_account_records(path)


def test_invalid_json_fails_validation(tmp_path) -> None:
    path = tmp_path / "accounts.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(InputValidationError, match="invalid JSON"):
        load_account_records(path)


def test_missing_input_file_maps_to_input_validation_error(tmp_path) -> None:
    with pytest.raises(InputValidationError, match="unable to read input file"):
        load_account_records(tmp_path / "missing.json")


@pytest.mark.parametrize("field_name", ["password", "secret", "sauce_password"])
def test_password_like_fields_are_rejected(field_name) -> None:
    raw = valid_record()
    raw[field_name] = "value"

    with pytest.raises(InputValidationError, match="password-like"):
        parse_account_record(raw)


@pytest.mark.parametrize("field_name", ["password", "secret", "sauce_password"])
def test_nested_password_like_fields_are_rejected(field_name) -> None:
    raw = valid_record()
    raw["checkout_profile"][field_name] = "value"

    with pytest.raises(InputValidationError, match="record.checkout_profile.*password-like"):
        parse_account_record(raw)


def test_all_sample_records_are_valid() -> None:
    accounts = load_account_records(ROOT / "data/saucedemo_accounts.json")

    assert all(isinstance(account, SauceDemoAccount) for account in accounts)


def test_sample_data_contains_exactly_required_usernames() -> None:
    accounts = load_account_records(ROOT / "data/saucedemo_accounts.json")

    assert {account.username for account in accounts} == REQUIRED_USERNAMES


def test_sample_data_contains_exactly_six_records() -> None:
    accounts = load_account_records(ROOT / "data/saucedemo_accounts.json")

    assert len(accounts) == 6


def test_sample_data_does_not_contain_passwords_or_workflow_control_flags() -> None:
    raw_records = json.loads((ROOT / "data/saucedemo_accounts.json").read_text(encoding="utf-8"))
    forbidden = {
        "password",
        "secret",
        "sauce_password",
        "skip",
        "pre_skip",
        "expected_failure",
    }

    for raw_record in raw_records:
        assert forbidden.isdisjoint(raw_record)
        assert forbidden.isdisjoint(raw_record["checkout_profile"])


@dataclass
class ConfigStub:
    saucedemo_input_path: str


@dataclass
class ContextStub:
    config: ConfigStub


def test_saucedemo_runner_load_items_reads_config_input_path(tmp_path) -> None:
    path = write_json(tmp_path / "accounts.json", [valid_record()])
    context = ContextStub(config=ConfigStub(saucedemo_input_path=str(path)))

    items = SauceDemoRunner().load_items(context)

    assert len(items) == 1
    assert items[0].username == "standard_user"


def test_invalid_input_maps_to_input_validation_failed_portal_error(tmp_path) -> None:
    path = write_json(tmp_path / "accounts.json", [{"username": "standard_user"}])
    context = ContextStub(config=ConfigStub(saucedemo_input_path=str(path)))

    with pytest.raises(PortalError) as error:
        SauceDemoRunner().load_items(context)

    assert error.value.reason is ReasonCode.INPUT_VALIDATION_FAILED
    assert "account_key" in error.value.detail


def test_schema_does_not_import_playwright_browser_or_page_modules() -> None:
    source = (ROOT / "src/portal_automation/portals/saucedemo/input_schema.py").read_text(
        encoding="utf-8"
    ).lower()

    assert "playwright" not in source
    assert "browser" not in source
    assert "page" not in source


def test_runner_does_not_import_playwright_directly() -> None:
    source = (ROOT / "src/portal_automation/portals/saucedemo/runner.py").read_text(
        encoding="utf-8"
    ).lower()

    for forbidden in (
        "import playwright",
        "from playwright",
        "sync_playwright",
        "async_playwright",
        "chromium.launch",
        "firefox.launch",
        "webkit.launch",
    ):
        assert forbidden not in source


def test_schema_source_does_not_import_persistence_or_sqlite_modules() -> None:
    source = (ROOT / "src/portal_automation/portals/saucedemo/input_schema.py").read_text(
        encoding="utf-8"
    )

    assert "persistence" not in source
    assert "sqlite" not in source


def test_source_and_sample_data_do_not_contain_demo_credentials() -> None:
    paths = [
        ROOT / "src/portal_automation/portals/saucedemo/input_schema.py",
        ROOT / "src/portal_automation/portals/saucedemo/runner.py",
        ROOT / "data/saucedemo_accounts.json",
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
