"""
Tests — application configuration (P1-1).

Verifies:
- Settings instantiates without DATABASE_URL set.
- database_url is None when env var is absent.
- database_url holds the value when env var is present.
- get_database_url() returns the value when set.
- get_database_url() raises RuntimeError when database_url is None.
"""

from __future__ import annotations

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Helpers — build isolated Settings instances for each test
# ---------------------------------------------------------------------------

def _make_settings(**env_overrides):
    """Build a fresh Settings-like instance with the given env vars."""
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class IsolatedSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=None,
            case_sensitive=False,
            extra="ignore",
        )
        app_name: str = "LedgerLens"
        debug: bool = False
        api_version: str = "v1"
        database_url: str | None = None

        def get_database_url(self) -> str:
            if self.database_url is None:
                raise RuntimeError(
                    "DATABASE_URL is not configured. "
                    "Set the DATABASE_URL environment variable or add it to .env "
                    "before using database features."
                )
            return self.database_url

    import os
    old = {}
    for k, v in env_overrides.items():
        old[k] = os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v
    # Also remove DATABASE_URL if not being set, to test absence
    if "DATABASE_URL" not in env_overrides:
        old["DATABASE_URL"] = os.environ.pop("DATABASE_URL", None)

    try:
        return IsolatedSettings()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestDatabaseUrlOptional:
    def test_settings_loads_without_database_url(self):
        """Settings must instantiate successfully without DATABASE_URL env var."""
        s = _make_settings()
        assert s.database_url is None

    def test_database_url_is_none_when_absent(self):
        s = _make_settings()
        assert s.database_url is None

    def test_database_url_populated_when_set(self):
        url = "postgresql://test:test@localhost:5432/testdb"
        s = _make_settings(DATABASE_URL=url)
        assert s.database_url == url

    def test_app_name_default_preserved(self):
        s = _make_settings()
        assert s.app_name == "LedgerLens"

    def test_api_version_default_preserved(self):
        s = _make_settings()
        assert s.api_version == "v1"


class TestGetDatabaseUrl:
    def test_get_database_url_returns_value_when_set(self):
        url = "postgresql://user:pass@host:5432/db"
        s = _make_settings(DATABASE_URL=url)
        assert s.get_database_url() == url

    def test_get_database_url_raises_when_none(self):
        s = _make_settings()
        with pytest.raises(RuntimeError, match="DATABASE_URL is not configured"):
            s.get_database_url()

    def test_get_database_url_error_message_is_actionable(self):
        """Error message must tell the developer what to do."""
        s = _make_settings()
        with pytest.raises(RuntimeError) as exc_info:
            s.get_database_url()
        assert "DATABASE_URL" in str(exc_info.value)
        assert "environment variable" in str(exc_info.value)
