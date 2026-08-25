"""API tests for P4-6 investigation controller integration."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.api.investigation import get_investigation_service
from app.main import app
from app.services.gemini import GeminiUnavailableError
from app.services.investigation import AgentInvestigationService
from app.services.reconciliation import ReconciliationService
from tests.reconciliation.conftest import make_clean_world

client = TestClient(app)

class FakeGemini:
    def __init__(self, payload: object = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls: list[dict[str, object]] = []

    def generate_structured_content(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.payload

class SpyInvestigationService:
    def __init__(self, gemini: FakeGemini) -> None:
        self.delegate = AgentInvestigationService(gemini_client=gemini)
        self.calls = 0

    def investigate(self, **kwargs: object):
        self.calls += 1
        return self.delegate.investigate(**kwargs)

@pytest.fixture
def clean_payload() -> dict:
    world = make_clean_world()
    return {
        "merchants": [item.model_dump(mode="json") for item in world.merchants],
        "payments": [item.model_dump(mode="json") for item in world.payments],
        "settlements": [item.model_dump(mode="json") for item in world.settlements],
        "bank_entries": [item.model_dump(mode="json") for item in world.bank_entries],
        "ledger_entries": [item.model_dump(mode="json") for item in world.ledger_entries],
        "batch_id": "BATCH_API",
        "target_payment_id": world.payments[0].payment_id,
    }


def _requires_investigation_payload(payload: dict) -> dict:
    corrupted = deepcopy(payload)
    corrupted["bank_entries"][0]["credit_amount"] = "1.00"
    return corrupted


@pytest.fixture
def override_service():
    services: list[SpyInvestigationService] = []

    def install(gemini: FakeGemini) -> SpyInvestigationService:
        service = SpyInvestigationService(gemini)
        services.append(service)
        app.dependency_overrides[get_investigation_service] = lambda: service
        return service

    yield install
    app.dependency_overrides.pop(get_investigation_service, None)

def test_successful_investigation_delegates_and_returns_result(clean_payload, override_service) -> None:
    service = override_service(FakeGemini({"investigation_confidence": "0.40"}))
    response = client.post("/api/v1/reconciliation/investigate", json=clean_payload)

    assert response.status_code == status.HTTP_200_OK
    assert service.calls == 1
    body = response.json()
    assert body["deterministic_reconciliation"]["batch_id"] == "BATCH_API"
    assert body["investigation_report"]["payment_id"] == clean_payload["target_payment_id"]

@pytest.mark.parametrize("target", ["", "   "])
def test_empty_or_whitespace_target_is_rejected(clean_payload, override_service, target) -> None:
    payload = {**clean_payload, "target_payment_id": target}
    response = client.post("/api/v1/reconciliation/investigate", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

def test_unknown_target_is_rejected(clean_payload, override_service) -> None:
    service = override_service(FakeGemini())
    payload = {**clean_payload, "target_payment_id": "PAY_UNKNOWN"}
    response = client.post("/api/v1/reconciliation/investigate", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert service.calls == 1

def test_recursive_float_is_rejected(clean_payload, override_service) -> None:
    payload = deepcopy(clean_payload)
    payload["payments"][0]["amount"] = 100.5
    response = client.post("/api/v1/reconciliation/investigate", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

@pytest.mark.parametrize("field", ["unknown_field", "ground_truth", "corruption_events", "observed_value"])
def test_forbidden_or_unknown_fields_are_rejected(clean_payload, override_service, field) -> None:
    payload = deepcopy(clean_payload)
    payload["payments"][0][field] = []
    response = client.post("/api/v1/reconciliation/investigate", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

def test_gemini_unavailable_returns_deterministic_fallback(clean_payload, override_service) -> None:
    service = override_service(FakeGemini(error=GeminiUnavailableError("offline")))
    response = client.post(
        "/api/v1/reconciliation/investigate",
        json=_requires_investigation_payload(clean_payload),
    )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["investigation_report"]["status"] == "UNAVAILABLE"
    assert body["investigation_report"]["investigation_confidence"] is None
    assert body["deterministic_reconciliation"]["human_review"] == 1
    assert "offline" in body["investigation_report"]["agent_explanation"]
    assert "ground_truth" not in response.text
    assert "corruption_events" not in response.text
    assert service.calls == 1

def test_invalid_gemini_output_returns_fallback(clean_payload, override_service) -> None:
    override_service(FakeGemini(payload="not-a-dict"))
    response = client.post(
        "/api/v1/reconciliation/investigate",
        json=_requires_investigation_payload(clean_payload),
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["investigation_report"]["status"] == "INVALID_OUTPUT"

def test_deterministic_decision_and_confidence_are_preserved(clean_payload, override_service) -> None:
    payload = deepcopy(clean_payload)
    payload["bank_entries"][0]["credit_amount"] = "1.00"
    override_service(
        FakeGemini(
            {
                "payment_id": "PAY_HALLUCINATED",
                "reconciliation_confidence": "1.00",
                "exception_codes": ["rec:E999"],
                "investigation_confidence": "0.25",
            }
        )
    )
    response = client.post("/api/v1/reconciliation/investigate", json=payload)

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["deterministic_reconciliation"]["decisions"][0]["decision"] == "HUMAN_REVIEW"
    assert body["deterministic_reconciliation"]["decisions"][0]["exception_codes"] != ["rec:E999"]
    assert body["investigation_report"]["reconciliation_confidence"] != "1.00"
    assert body["investigation_report"]["investigation_confidence"] == "0.25"

def test_clean_auto_match_does_not_call_gemini(clean_payload, override_service) -> None:
    gemini = FakeGemini({"investigation_confidence": "0.99"})
    override_service(gemini)
    response = client.post("/api/v1/reconciliation/investigate", json=clean_payload)

    assert response.status_code == status.HTTP_200_OK
    assert gemini.calls == []
    assert response.json()["deterministic_reconciliation"]["auto_matched"] == 1

def test_input_batch_is_not_mutated(clean_payload, override_service) -> None:
    original = deepcopy(clean_payload)
    override_service(FakeGemini(payload={"investigation_confidence": "0.30"}))
    response = client.post("/api/v1/reconciliation/investigate", json=clean_payload)

    assert response.status_code == status.HTTP_200_OK
    assert clean_payload == original

def test_existing_reconciliation_endpoint_remains_functional(clean_payload) -> None:
    payload = {key: value for key, value in clean_payload.items() if key != "target_payment_id"}
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["reconciliation_result"]["auto_matched"] == 1