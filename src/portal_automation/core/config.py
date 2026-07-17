import os
from dataclasses import dataclass, field

TRUE_VALUES = {"true", "1", "yes", "on"}
FALSE_VALUES = {"false", "0", "no", "off"}


def _env_value(key: str, default: str) -> str:
    """Read an environment value with a string default.

    Args:
        key: Environment variable name.
        default: Value to use when the variable is unset.

    Returns:
        Environment value or the provided default.
    """
    return os.environ.get(key, default)


def _optional_env_value(key: str, default: str = "") -> str | None:
    """Read an environment value and normalize empty strings to ``None``.

    Args:
        key: Environment variable name.
        default: Value to use when the variable is unset.

    Returns:
        Non-empty string value, otherwise ``None``.
    """
    value = _env_value(key, default)
    return value or None


def _optional_int_env_value(key: str) -> int | None:
    """Read an optional integer environment value.

    Args:
        key: Environment variable name.

    Returns:
        Parsed integer, or ``None`` when unset or blank.

    Raises:
        ValueError: If the value is present but not an integer.
    """
    value = _optional_env_value(key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer value") from exc


def _bool_env_value(key: str, default: str) -> bool:
    """Read a boolean environment value.

    Args:
        key: Environment variable name.
        default: String default used when the variable is unset.

    Returns:
        Parsed boolean value.

    Raises:
        ValueError: If the value is not a supported boolean spelling.
    """
    value = _env_value(key, default).strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError(f"{key} must be a boolean value")


def _int_env_value(key: str, default: str) -> int:
    """Read a required integer-like environment value.

    Args:
        key: Environment variable name.
        default: String default used when the variable is unset.

    Returns:
        Parsed integer value.

    Raises:
        ValueError: If the value is not an integer.
    """
    value = _env_value(key, default)
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer value") from exc


@dataclass
class AppConfig:
    db_path: str
    artifacts_dir: str
    business_date: str | None
    headless: bool
    default_timeout_seconds: int
    orangehrm_timeout_seconds: int | None
    saucedemo_timeout_seconds: int | None
    max_retries: int
    stale_item_timeout_seconds: int
    orangehrm_base_url: str
    orangehrm_username: str
    orangehrm_password: str | None = field(repr=False)
    orangehrm_input_path: str
    saucedemo_base_url: str
    saucedemo_password: str | None = field(repr=False)
    saucedemo_input_path: str
    email_backend: str
    report_email_to: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None = field(repr=False)
    smtp_from: str | None
    smtp_to: str | None
    smtp_use_tls: bool
    playwright_trace_on_failure: bool
    playwright_screenshot_on_failure: bool
    visible_browser_pause_on_error_seconds: int
    visible_browser_pause_on_result_seconds: int
    playwright_persistent_profile_dir: str | None

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Build application configuration from environment variables.

        Returns:
            Fully populated ``AppConfig`` with defaults applied.

        Raises:
            ValueError: If any typed environment value cannot be parsed or validated.
        """
        # Keep all runtime defaults in one place so CLI and tests resolve config the same way.
        return cls(
            db_path=_env_value("DB_PATH", "artifacts/portal_automation.sqlite"),
            artifacts_dir=_env_value("ARTIFACTS_DIR", "artifacts"),
            business_date=_optional_env_value("BUSINESS_DATE"),
            headless=_bool_env_value("HEADLESS", "true"),
            default_timeout_seconds=_int_env_value("DEFAULT_TIMEOUT_SECONDS", "30"),
            orangehrm_timeout_seconds=_optional_int_env_value("ORANGEHRM_TIMEOUT_SECONDS"),
            saucedemo_timeout_seconds=_optional_int_env_value("SAUCEDEMO_TIMEOUT_SECONDS"),
            max_retries=_int_env_value("MAX_RETRIES", "2"),
            stale_item_timeout_seconds=_int_env_value("STALE_ITEM_TIMEOUT_SECONDS", "300"),
            orangehrm_base_url=_env_value(
                "ORANGEHRM_BASE_URL",
                "https://opensource-demo.orangehrmlive.com",
            ),
            orangehrm_username=_env_value("ORANGEHRM_USERNAME", "Admin"),
            orangehrm_password=_optional_env_value("ORANGEHRM_PASSWORD"),
            orangehrm_input_path=_env_value(
                "ORANGEHRM_INPUT_PATH",
                "data/orangehrm_employees.json",
            ),
            saucedemo_base_url=_env_value("SAUCEDEMO_BASE_URL", "https://www.saucedemo.com"),
            saucedemo_password=_optional_env_value("SAUCEDEMO_PASSWORD"),
            saucedemo_input_path=_env_value(
                "SAUCEDEMO_INPUT_PATH",
                "data/saucedemo_accounts.json",
            ),
            email_backend=_env_value("EMAIL_BACKEND", "dry_run"),
            report_email_to=_optional_env_value("REPORT_EMAIL_TO"),
            smtp_host=_optional_env_value("SMTP_HOST"),
            smtp_port=_int_env_value("SMTP_PORT", "587"),
            smtp_username=_optional_env_value("SMTP_USERNAME"),
            smtp_password=_optional_env_value("SMTP_PASSWORD"),
            smtp_from=_optional_env_value("SMTP_FROM"),
            smtp_to=_optional_env_value("SMTP_TO"),
            smtp_use_tls=_bool_env_value("SMTP_USE_TLS", "true"),
            playwright_trace_on_failure=_bool_env_value("PLAYWRIGHT_TRACE_ON_FAILURE", "true"),
            playwright_screenshot_on_failure=_bool_env_value(
                "PLAYWRIGHT_SCREENSHOT_ON_FAILURE",
                "true",
            ),
            visible_browser_pause_on_error_seconds=_int_env_value(
                "VISIBLE_BROWSER_PAUSE_ON_ERROR_SECONDS",
                "0",
            ),
            visible_browser_pause_on_result_seconds=_int_env_value(
                "VISIBLE_BROWSER_PAUSE_ON_RESULT_SECONDS",
                _env_value("VISIBLE_BROWSER_PAUSE_ON_ERROR_SECONDS", "10"),
            ),
            playwright_persistent_profile_dir=_optional_env_value(
                "PLAYWRIGHT_PERSISTENT_PROFILE_DIR"
            ),
        )

    def __post_init__(self) -> None:
        """Validate timeout values after dataclass initialization.

        Raises:
            ValueError: If any configured timeout is less than or equal to zero.
        """
        _validate_positive_timeout("DEFAULT_TIMEOUT_SECONDS", self.default_timeout_seconds)
        _validate_optional_positive_timeout(
            "ORANGEHRM_TIMEOUT_SECONDS",
            self.orangehrm_timeout_seconds,
        )
        _validate_optional_positive_timeout(
            "SAUCEDEMO_TIMEOUT_SECONDS",
            self.saucedemo_timeout_seconds,
        )
        _validate_non_negative_timeout(
            "VISIBLE_BROWSER_PAUSE_ON_ERROR_SECONDS",
            self.visible_browser_pause_on_error_seconds,
        )
        _validate_non_negative_timeout(
            "VISIBLE_BROWSER_PAUSE_ON_RESULT_SECONDS",
            self.visible_browser_pause_on_result_seconds,
        )

    def portal_timeout_seconds(self, portal_name: str) -> int:
        """Return the timeout configured for a portal.

        Args:
            portal_name: Portal key, case-insensitive and whitespace-tolerant.

        Returns:
            Portal-specific timeout when configured, otherwise the global default.
        """
        normalized = portal_name.strip().lower()
        # Portal-specific overrides let slower sites wait longer without penalizing faster ones.
        if normalized == "orangehrm" and self.orangehrm_timeout_seconds is not None:
            return self.orangehrm_timeout_seconds
        if normalized == "saucedemo" and self.saucedemo_timeout_seconds is not None:
            return self.saucedemo_timeout_seconds
        return self.default_timeout_seconds

    def default_input_path(self, portal_name: str) -> str:
        """Return the default input path for a registered portal key.

        Args:
            portal_name: Portal key.

        Returns:
            Configured input path for that portal.

        Raises:
            ValueError: If the portal key is unknown.
        """
        if portal_name == "orangehrm":
            return self.orangehrm_input_path
        if portal_name == "saucedemo":
            return self.saucedemo_input_path
        raise ValueError(f"Unknown portal name: {portal_name}")


def _validate_positive_timeout(name: str, value: int) -> None:
    """Validate that a timeout is positive.

    Args:
        name: Configuration key used in the error message.
        value: Timeout value in seconds.

    Raises:
        ValueError: If ``value`` is less than or equal to zero.
    """
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")


def _validate_optional_positive_timeout(name: str, value: int | None) -> None:
    """Validate an optional timeout when present.

    Args:
        name: Configuration key used in the error message.
        value: Optional timeout value in seconds.

    Raises:
        ValueError: If ``value`` is present and not positive.
    """
    if value is not None:
        _validate_positive_timeout(name, value)


def _validate_non_negative_timeout(name: str, value: int) -> None:
    """Validate that a timeout-like value is zero or positive.

    Args:
        name: Configuration key used in the error message.
        value: Timeout-like value in seconds.

    Raises:
        ValueError: If ``value`` is negative.
    """
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")
