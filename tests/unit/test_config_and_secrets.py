from pathlib import Path

import pytest

from portal_automation.core.config import AppConfig
from portal_automation.core.secrets import SecretsLoader

ROOT = Path(__file__).resolve().parents[2]
CONFIG_ENV_KEYS = (
    "DB_PATH",
    "ARTIFACTS_DIR",
    "BUSINESS_DATE",
    "HEADLESS",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_RETRIES",
    "STALE_ITEM_TIMEOUT_SECONDS",
    "ORANGEHRM_BASE_URL",
    "ORANGEHRM_USERNAME",
    "ORANGEHRM_PASSWORD",
    "ORANGEHRM_INPUT_PATH",
    "SAUCEDEMO_BASE_URL",
    "SAUCEDEMO_PASSWORD",
    "SAUCEDEMO_INPUT_PATH",
    "EMAIL_BACKEND",
    "REPORT_EMAIL_TO",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "SMTP_TO",
)


def clear_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_app_config_from_env_returns_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)

    config = AppConfig.from_env()

    assert config.db_path == "artifacts/portal_automation.sqlite"
    assert config.artifacts_dir == "artifacts"
    assert config.business_date is None
    assert config.headless is True
    assert config.default_timeout_seconds == 30
    assert config.max_retries == 2
    assert config.stale_item_timeout_seconds == 300
    assert config.orangehrm_base_url == "https://opensource-demo.orangehrmlive.com"
    assert config.orangehrm_username == "Admin"
    assert config.orangehrm_password is None
    assert config.orangehrm_input_path == "data/orangehrm_employees.json"
    assert config.saucedemo_base_url == "https://www.saucedemo.com"
    assert config.saucedemo_password is None
    assert config.saucedemo_input_path == "data/saucedemo_accounts.json"
    assert config.email_backend == "dry_run"
    assert config.report_email_to is None
    assert config.smtp_host is None
    assert config.smtp_port == 587
    assert config.smtp_username is None
    assert config.smtp_password is None
    assert config.smtp_from is None
    assert config.smtp_to is None


def test_app_config_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("DB_PATH", "custom/db.sqlite")
    monkeypatch.setenv("ARTIFACTS_DIR", "custom-artifacts")
    monkeypatch.setenv("BUSINESS_DATE", "2026-06-28")
    monkeypatch.setenv("HEADLESS", "false")
    monkeypatch.setenv("DEFAULT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("MAX_RETRIES", "4")
    monkeypatch.setenv("STALE_ITEM_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("ORANGEHRM_BASE_URL", "https://orange.example")
    monkeypatch.setenv("ORANGEHRM_USERNAME", "operator")
    monkeypatch.setenv("ORANGEHRM_PASSWORD", "orange-token")
    monkeypatch.setenv("ORANGEHRM_INPUT_PATH", "custom/orange.json")
    monkeypatch.setenv("SAUCEDEMO_BASE_URL", "https://sauce.example")
    monkeypatch.setenv("SAUCEDEMO_PASSWORD", "sauce-token")
    monkeypatch.setenv("SAUCEDEMO_INPUT_PATH", "custom/sauce.json")
    monkeypatch.setenv("EMAIL_BACKEND", "smtp")
    monkeypatch.setenv("REPORT_EMAIL_TO", "reviewer@example.com")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-token")
    monkeypatch.setenv("SMTP_FROM", "from@example.com")
    monkeypatch.setenv("SMTP_TO", "to@example.com")

    config = AppConfig.from_env()

    assert config.db_path == "custom/db.sqlite"
    assert config.artifacts_dir == "custom-artifacts"
    assert config.business_date == "2026-06-28"
    assert config.headless is False
    assert config.default_timeout_seconds == 45
    assert config.max_retries == 4
    assert config.stale_item_timeout_seconds == 600
    assert config.orangehrm_base_url == "https://orange.example"
    assert config.orangehrm_username == "operator"
    assert config.orangehrm_password == "orange-token"
    assert config.orangehrm_input_path == "custom/orange.json"
    assert config.saucedemo_base_url == "https://sauce.example"
    assert config.saucedemo_password == "sauce-token"
    assert config.saucedemo_input_path == "custom/sauce.json"
    assert config.email_backend == "smtp"
    assert config.report_email_to == "reviewer@example.com"
    assert config.smtp_host == "smtp.example.com"
    assert config.smtp_port == 2525
    assert config.smtp_username == "smtp-user"
    assert config.smtp_password == "smtp-token"
    assert config.smtp_from == "from@example.com"
    assert config.smtp_to == "to@example.com"


def test_empty_optional_env_values_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    optional_keys = (
        "BUSINESS_DATE",
        "ORANGEHRM_PASSWORD",
        "SAUCEDEMO_PASSWORD",
        "REPORT_EMAIL_TO",
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "SMTP_TO",
    )
    for key in optional_keys:
        monkeypatch.setenv(key, "")

    config = AppConfig.from_env()

    assert config.business_date is None
    assert config.orangehrm_password is None
    assert config.saucedemo_password is None
    assert config.report_email_to is None
    assert config.smtp_host is None
    assert config.smtp_username is None
    assert config.smtp_password is None
    assert config.smtp_from is None
    assert config.smtp_to is None


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_headless_parses_true_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HEADLESS", value)

    assert AppConfig.from_env().headless is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off"])
def test_headless_parses_false_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HEADLESS", value)

    assert AppConfig.from_env().headless is False


def test_invalid_boolean_raises_value_error_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("HEADLESS", "sometimes")

    with pytest.raises(ValueError, match="HEADLESS"):
        AppConfig.from_env()


def test_invalid_integer_raises_value_error_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("MAX_RETRIES", "many")

    with pytest.raises(ValueError, match="MAX_RETRIES"):
        AppConfig.from_env()


def test_default_input_path_returns_configured_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("ORANGEHRM_INPUT_PATH", "inputs/orange.json")
    monkeypatch.setenv("SAUCEDEMO_INPUT_PATH", "inputs/sauce.json")
    config = AppConfig.from_env()

    assert config.default_input_path("orangehrm") == "inputs/orange.json"
    assert config.default_input_path("saucedemo") == "inputs/sauce.json"


def test_default_input_path_rejects_unknown_portal(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    config = AppConfig.from_env()

    with pytest.raises(ValueError, match="unknown"):
        config.default_input_path("unknown")


def test_secrets_loader_returns_supported_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("ORANGEHRM_PASSWORD", "orange-token")
    monkeypatch.setenv("SAUCEDEMO_PASSWORD", "sauce-token")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-token")
    loader = SecretsLoader(AppConfig.from_env())

    assert loader.get("ORANGEHRM_PASSWORD") == "orange-token"
    assert loader.get("SAUCEDEMO_PASSWORD") == "sauce-token"
    assert loader.get("SMTP_PASSWORD") == "smtp-token"


def test_secrets_loader_returns_none_for_unknown_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_env(monkeypatch)
    loader = SecretsLoader(AppConfig.from_env())

    assert loader.get("UNKNOWN") is None


def test_config_and_secrets_repr_do_not_expose_secret_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_config_env(monkeypatch)
    monkeypatch.setenv("ORANGEHRM_PASSWORD", "orange-token")
    monkeypatch.setenv("SAUCEDEMO_PASSWORD", "sauce-token")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-token")
    config = AppConfig.from_env()
    loader = SecretsLoader(config)

    config_repr = repr(config)
    loader_repr = repr(loader)

    assert "orange-token" not in config_repr
    assert "sauce-token" not in config_repr
    assert "smtp-token" not in config_repr
    assert "orange-token" not in loader_repr
    assert "sauce-token" not in loader_repr
    assert "smtp-token" not in loader_repr


def test_demo_credentials_do_not_appear_in_src() -> None:
    matches = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src").rglob("*.py")
        if "secret_sauce" in path.read_text(encoding="utf-8")
        or "admin123" in path.read_text(encoding="utf-8")
    ]

    assert matches == []


def test_forbidden_modules_were_not_created() -> None:
    forbidden_paths = [
        "src/portal_automation/core/logging.py",
    ]

    assert [path for path in forbidden_paths if (ROOT / path).exists()] == []
