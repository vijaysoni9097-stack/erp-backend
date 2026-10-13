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
    sync_enabled: bool = False
    sync_device_secret: str | None = None
    sync_device_id: str | None = None
    sync_pharmacy_id: str | None = None
    supabase_project_url: str | None = None
    supabase_publishable_key: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_starttls: bool = True
    password_reset_url: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
