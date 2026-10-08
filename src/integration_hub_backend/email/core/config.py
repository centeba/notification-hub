"""Email service configuration."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from smart_llm.secret_guard import enforce_no_placeholder_secrets


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = "local"

    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = False

    # Empty = unset: the send route fails closed (503) rather than accepting a
    # guessable default.
    INTERNAL_SERVICE_SECRET: str = ""

    DEFAULT_FROM_ADDRESS: str = "notifications@example.com"
    DEFAULT_FROM_NAME: str = "Notification Hub"

    @model_validator(mode="after")
    def _reject_placeholder_secrets(self) -> "Settings":
        enforce_no_placeholder_secrets(
            self.ENVIRONMENT,
            INTERNAL_SERVICE_SECRET=self.INTERNAL_SERVICE_SECRET,
            SMTP_PASSWORD=self.SMTP_PASSWORD,
        )
        return self


settings = Settings()
