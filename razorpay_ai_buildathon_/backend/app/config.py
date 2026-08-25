"""
LedgerLens — application configuration.

Reads from environment variables (or .env file if present).
All fields are typed via Pydantic Settings — no raw os.environ access.

DATABASE_URL is optional in Phases 1–3 (no database code is active).
It becomes required when Phase 4 persistence features are enabled.
Use settings.get_database_url() to retrieve it — that method raises
a clear RuntimeError if the value is not set, rather than crashing at
import time.
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

    # PostgreSQL — optional until Phase 4 adds connection logic.
    # Set DATABASE_URL in the environment or .env file when persistence
    # features are enabled. Do not add a default containing credentials.
    database_url: str | None = None

    # Gemini AI configuration
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 3.0
    gemini_max_retries: int = 3

    def get_database_url(self) -> str:
        """
        Return the database URL.

        Raises RuntimeError with a clear message if DATABASE_URL is not
        configured, rather than crashing silently at import time.
        """
        if self.database_url is None:
            raise RuntimeError(
                "DATABASE_URL is not configured. "
                "Set the DATABASE_URL environment variable or add it to .env "
                "before using database features."
            )
        return self.database_url


settings = Settings()
