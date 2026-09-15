"""Email service configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = False

    INTERNAL_SERVICE_SECRET: str = "changethis"

    DEFAULT_FROM_ADDRESS: str = "notifications@example.com"
    DEFAULT_FROM_NAME: str = "Notification Hub"


settings = Settings()
