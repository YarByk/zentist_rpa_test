from dataclasses import dataclass, field

from portal_automation.core.config import AppConfig


class MissingSecretError(ValueError):
    """Raised when a required runtime secret is missing."""


@dataclass
class SecretsLoader:
    config: AppConfig = field(repr=False)

    def get(self, key: str) -> str | None:
        secrets = {
            "ORANGEHRM_PASSWORD": self.config.orangehrm_password,
            "SAUCEDEMO_PASSWORD": self.config.saucedemo_password,
            "SMTP_PASSWORD": self.config.smtp_password,
        }
        return secrets.get(key)

    def require(self, key: str) -> str:
        value = self.get(key)
        if not isinstance(value, str) or not value.strip():
            raise MissingSecretError(f"{key} is required for this runtime path.")
        return value.strip()
