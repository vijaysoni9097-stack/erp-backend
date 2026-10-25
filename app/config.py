from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    app_name: str = "Hospital Pharmacy ERP API"
    debug: bool = True
    database_schema: str = Field(default="erp_app", pattern=r"^[a-z][a-z0-9_]{0,62}$")
    require_postgres: bool = False
    cors_origins: list[str] = []
    database_url: str = "sqlite:///./temp.db"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_starttls: bool = True
    smtp_cc_email: str | None = None
    user_login_url: str | None = None
    password_reset_url: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
