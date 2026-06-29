import json
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any

PASSWORD_LIKE_FIELDS = frozenset({"password", "secret", "sauce_password"})


class InputValidationError(ValueError):
    """Raised when Sauce Demo account input cannot be validated."""


@dataclass(frozen=True)
class CheckoutProfile:
    first_name: str
    last_name: str
    postal_code: str


@dataclass(frozen=True)
class SauceDemoAccount:
    account_key: str
    username: str
    items_to_add: int
    checkout_profile: CheckoutProfile


def parse_account_record(raw: dict[str, Any]) -> SauceDemoAccount:
    _reject_password_like_fields(raw, "record")
    account_key = _required_string(raw, "account_key", "record")
    username = _required_string(raw, "username", "record")
    items_to_add = _items_to_add(raw)
    profile_raw = _required_object(raw, "checkout_profile", "record")
    _reject_password_like_fields(profile_raw, "record.checkout_profile")
    return SauceDemoAccount(
        account_key=account_key,
        username=username,
        items_to_add=items_to_add,
        checkout_profile=CheckoutProfile(
            first_name=_required_string(profile_raw, "first_name", "record.checkout_profile"),
            last_name=_required_string(profile_raw, "last_name", "record.checkout_profile"),
            postal_code=_required_string(profile_raw, "postal_code", "record.checkout_profile"),
        ),
    )


def load_account_records(path: str | Path) -> list[SauceDemoAccount]:
    input_path = Path(path)
    try:
        parsed = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputValidationError(f"unable to read input file '{input_path}': {exc}") from exc
    except JSONDecodeError as exc:
        raise InputValidationError(f"invalid JSON in '{input_path}': {exc.msg}") from exc

    if not isinstance(parsed, list):
        raise InputValidationError("top-level input must be a list")

    accounts = []
    for index, raw_record in enumerate(parsed):
        if not isinstance(raw_record, dict):
            raise InputValidationError(f"record[{index}]: must be an object")
        try:
            accounts.append(parse_account_record(raw_record))
        except InputValidationError as exc:
            raise InputValidationError(f"record[{index}]: {exc}") from exc
    return accounts


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


def _items_to_add(raw: dict[str, Any]) -> int:
    value = raw.get("items_to_add", 3)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InputValidationError("record.items_to_add: must be a positive integer")
    return value


def _reject_password_like_fields(raw: dict[str, Any], context: str) -> None:
    forbidden = sorted(PASSWORD_LIKE_FIELDS.intersection(raw))
    if forbidden:
        raise InputValidationError(
            f"{context}: password-like fields are not allowed: {', '.join(forbidden)}"
        )
