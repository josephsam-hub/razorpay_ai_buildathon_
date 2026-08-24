"""
Phase 1 test — health endpoint.

Verifies:
- GET /health returns HTTP 200
- response body has correct shape
- status field is "ok"
- service name is present
- version field is present

DATABASE_URL is set as an environment variable before the app is imported
so that Pydantic Settings does not raise a validation error during tests.
This is a placeholder value — no real database connection is made in Phase 1.
"""

import os

# Must be set before app imports so Pydantic Settings can resolve DATABASE_URL.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://ledgerlens:CHANGE_ME@localhost:5432/ledgerlens",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_shape() -> None:
    response = client.get("/health")
    body = response.json()
    assert "status" in body
    assert "service" in body
    assert "version" in body


def test_health_status_is_ok() -> None:
    response = client.get("/health")
    assert response.json()["status"] == "ok"


def test_health_service_name_is_present() -> None:
    response = client.get("/health")
    assert len(response.json()["service"]) > 0


def test_health_content_type_is_json() -> None:
    response = client.get("/health")
    assert "application/json" in response.headers["content-type"]
