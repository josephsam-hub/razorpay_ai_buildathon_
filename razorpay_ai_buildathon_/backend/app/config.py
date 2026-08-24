"""
LedgerLens — application configuration.

Reads from environment variables (or .env file if present).
All fields are typed via Pydantic Settings — no raw os.environ access.

DATABASE_URL must be set explicitly in the environment or .env file.
The application will NOT start if DATABASE_URL is missing — this is intentional.
Do not add a default value containing credentials.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "LedgerLens"
    debug: bool = False
    api_version: str = "v1"

    # PostgreSQL — Phase 2 will add connection logic.
    # Must be explicitly set via environment variable or .env file.
    # No default: missing DATABASE_URL will raise a clear error at startup.
    database_url: str


settings = Settings()
