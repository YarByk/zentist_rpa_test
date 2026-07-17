from dataclasses import dataclass, field

from portal_automation.core.config import AppConfig


class MissingSecretError(ValueError):
    """Raised when a required runtime secret is missing."""


@dataclass
class SecretsLoader:
    config: AppConfig = field(repr=False)

    def get(self, key: str) -> str | None:
        """Return an optional secret from parsed runtime config.

        Args:
            key: Environment-style secret name, such as ``ORANGEHRM_PASSWORD``.

        Returns:
            Secret value when present, otherwise ``None``.
        """
        # Map environment-style secret names onto the already-parsed config object.
        secrets = {
            "ORANGEHRM_PASSWORD": self.config.orangehrm_password,
            "SAUCEDEMO_PASSWORD": self.config.saucedemo_password,
            "SMTP_PASSWORD": self.config.smtp_password,
        }
        return secrets.get(key)

    def require(self, key: str) -> str:
        """Return a required secret or fail with a clear error.

        Args:
            key: Environment-style secret name, such as ``SAUCEDEMO_PASSWORD``.

        Returns:
            Trimmed secret value.

        Raises:
            MissingSecretError: If the secret is missing or blank.
        """
        value = self.get(key)
        if not isinstance(value, str) or not value.strip():
            raise MissingSecretError(f"{key} is required for this runtime path.")
        return value.strip()
