"""
LedgerLens — Gemini Client Abstraction.
Defines the configurable interface for communicating with the Gemini API.

Gemini is optional. Missing SDK, missing credentials, timeouts, and provider
errors must surface as GeminiUnavailableError. They must never change a
deterministic reconciliation result.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Type

from pydantic import BaseModel, ValidationError

from app.config import settings


class GeminiUnavailableError(Exception):
    """Raised when Gemini API is unconfigured, rate-limited, times out, or offline."""


class GeminiTransientError(Exception):
    """Internal: provider failure that may be retried."""


_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_TRANSIENT_NAME_MARKERS = (
    "timeout",
    "timed out",
    "unavailable",
    "rate limit",
    "resourceexhausted",
    "too many requests",
    "connection",
    "temporarily",
)


class GeminiClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.api_key = api_key or settings.gemini_api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or settings.gemini_model
        self.timeout = timeout_seconds if timeout_seconds is not None else settings.gemini_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.gemini_max_retries
        self._sleeper = sleeper or time.sleep

    def _redact(self, msg: str) -> str:
        if not self.api_key:
            return msg
        return msg.replace(self.api_key, "[REDACTED_API_KEY]")

    def get_client(self) -> Any:
        """
        Instantiates and returns the official google-genai Client.
        Raises GeminiUnavailableError if API key is not configured.
        """
        if not self.api_key:
            raise GeminiUnavailableError("Gemini API key is not configured.")

        try:
            from google import genai
            return genai.Client(api_key=self.api_key, http_options={"timeout": int(self.timeout)})
        except GeminiUnavailableError:
            raise
        except Exception as e:
            raise GeminiUnavailableError(
                f"Failed to initialize Gemini Client: {self._redact(str(e))}"
            ) from e

    def _is_transient(self, exc: BaseException) -> bool:
        if isinstance(exc, (GeminiTransientError, TimeoutError, ConnectionError)):
            return True
        code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        if code in _TRANSIENT_STATUS_CODES:
            return True
        haystack = f"{type(exc).__name__} {exc}".lower()
        return any(marker in haystack for marker in _TRANSIENT_NAME_MARKERS)

    def _backoff_seconds(self, attempt_index: int) -> float:
        # attempt_index is 0-based for the failure that just occurred
        return min(2.0, 0.5 * (2 ** attempt_index))

    def _invoke_generate(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        system_instruction: str | None,
    ) -> str:
        client = self.get_client()
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            system_instruction=system_instruction,
        )
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return getattr(response, "text", None) or ""

    def generate_structured_content(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        system_instruction: str | None = None,
    ) -> BaseModel:
        """
        Calls Gemini to generate content conforming to response_schema.

        Permanent failures (missing key, malformed JSON, schema validation)
        are not retried. Transient provider failures are retried up to
        max_retries attempts. Failures never mutate caller state.
        """
        if not self.api_key:
            raise GeminiUnavailableError("Gemini API key is not configured.")

        attempts = max(1, int(self.max_retries))
        last_error: BaseException | None = None

        for attempt in range(attempts):
            try:
                text = self._invoke_generate(prompt, response_schema, system_instruction)
                if not text:
                    raise GeminiTransientError("Gemini returned an empty response.")
                return response_schema.model_validate_json(text)
            except GeminiUnavailableError:
                raise
            except ValidationError as e:
                raise GeminiUnavailableError(
                    f"Gemini API request failed: {self._redact(str(e))}"
                ) from e
            except Exception as e:
                if self._is_transient(e) and attempt < attempts - 1:
                    last_error = e
                    self._sleeper(self._backoff_seconds(attempt))
                    continue
                raise GeminiUnavailableError(
                    f"Gemini API request failed: {self._redact(str(e))}"
                ) from e

        raise GeminiUnavailableError(
            f"Gemini API request failed: {self._redact(str(last_error))}"
        )
