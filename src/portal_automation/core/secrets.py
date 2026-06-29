from dataclasses import dataclass, field

from portal_automation.core.config import AppConfig


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
