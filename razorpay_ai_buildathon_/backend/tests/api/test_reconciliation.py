"""
LedgerLens — API Integration Tests
==================================
Verifies safety boundaries, validation rules, error codes, and correctness
of the POST /api/v1/reconciliation/run endpoint.
"""

from __future__ import annotations

import json
from decimal import Decimal
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.main import app
from app.services.reconciliation import ReconciliationService
from app.models.reconciliation_input import from_observed_world
from tests.reconciliation.conftest import (
    make_clean_world,
    make_merchant,
    make_payment,
    make_settlement,
    make_bank_entry,
)

client = TestClient(app)


def _build_valid_payload() -> dict:
    """Helper to build a valid JSON-serialisable payload using clean data."""
    observed = make_clean_world()
    return {
        "merchants": [m.model_dump(mode="json") for m in observed.merchants],
        "payments": [p.model_dump(mode="json") for p in observed.payments],
        "settlements": [s.model_dump(mode="json") for s in observed.settlements],
        "bank_entries": [b.model_dump(mode="json") for b in observed.bank_entries],
        "ledger_entries": [le.model_dump(mode="json") for le in observed.ledger_entries],
        "batch_id": "BATCH_TEST_001",
    }


# ── Health Endpoint Regression Check ─────────────────────────────────────────

def test_health_endpoint_regression() -> None:
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ok"


# ── Valid Requests & Parity Checks ───────────────────────────────────────────

def test_run_reconciliation_valid_clean_batch() -> None:
    payload = _build_valid_payload()
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    assert "reconciliation_result" in body
    assert "exceptions" in body

    res = body["reconciliation_result"]
    assert res["batch_id"] == "BATCH_TEST_001"
    assert res["total_records"] == 1
    assert res["auto_matched"] == 1
    assert res["human_review"] == 0
    assert len(res["decisions"]) == 1
    assert res["decisions"][0]["decision"] == "AUTO_MATCH"


def test_run_reconciliation_corrupted_batch() -> None:
    # Setup batch with a settlement net mismatch to trigger an exception
    merchant = make_merchant(mid="M_001")
    p1 = make_payment(pid="PAY_1", amount="100.00", merchant_id="M_001")

    # Net net amount matches gross - fee, but bank credit will differ
    s1 = make_settlement(
        sid="SET_1",
        merchant_id="M_001",
        payment_ids=["PAY_1"],
        gross="100.00",
        fee="2.00",
        net="98.00",
        settlement_ref="REF_1"
    )
    b1 = make_bank_entry(bid="B_001", settlement_ref="REF_1", credit="90.00")

    payload = {
        "merchants": [merchant.model_dump(mode="json")],
        "payments": [p1.model_dump(mode="json")],
        "settlements": [s1.model_dump(mode="json")],
        "bank_entries": [b1.model_dump(mode="json")],
        "ledger_entries": [],
        "batch_id": "BATCH_CORRUPT"
    }

    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    res = body["reconciliation_result"]
    exceptions = body["exceptions"]

    assert res["auto_matched"] == 0
    assert res["human_review"] == 1
    assert len(exceptions) == 1
    assert exceptions[0]["payment_id"] == "PAY_1"


def test_run_reconciliation_empty_batch() -> None:
    payload = {
        "merchants": [],
        "payments": [],
        "settlements": [],
        "bank_entries": [],
        "ledger_entries": [],
        "batch_id": ""
    }
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    res = body["reconciliation_result"]
    assert res["batch_id"] == "BATCH_EMPTY"
    assert res["total_records"] == 0


# ── Invalid Request & Numeric Validation Checks ──────────────────────────────

def test_run_reconciliation_malformed_json() -> None:
    headers = {"Content-Type": "application/json"}
    response = client.post("/api/v1/reconciliation/run", data="invalid json payload", headers=headers)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_run_reconciliation_float_rejected() -> None:
    payload = _build_valid_payload()
    # Inject float in payment amount
    payload["payments"][0]["amount"] = 100.50
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Float values are not allowed" in response.text


def test_run_reconciliation_invalid_decimal_string() -> None:
    payload = _build_valid_payload()
    # Inject unparseable decimal string
    payload["payments"][0]["amount"] = "one-hundred-dollars"
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_run_reconciliation_invalid_date() -> None:
    payload = _build_valid_payload()
    # Inject invalid date
    payload["payments"][0]["payment_date"] = "2026-15-40"
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ── Security & Isolation Boundary Checks ─────────────────────────────────────

def test_run_reconciliation_forbidden_ground_truth() -> None:
    payload = _build_valid_payload()
    payload["ground_truth"] = []
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Forbidden field" in response.text


def test_run_reconciliation_forbidden_corruption_events() -> None:
    payload = _build_valid_payload()
    payload["corruption_events"] = []
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Forbidden field" in response.text


def test_run_reconciliation_forbidden_nested_corruption_id() -> None:
    payload = _build_valid_payload()
    payload["payments"][0]["corruption_id"] = "CE_123"
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Forbidden field" in response.text


def test_run_reconciliation_forbidden_nested_observed_value() -> None:
    payload = _build_valid_payload()
    payload["payments"][0]["observed_value"] = "98.00"
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Forbidden field" in response.text


def test_run_reconciliation_unknown_field_rejected() -> None:
    payload = _build_valid_payload()
    payload["extra_field"] = "random-data"
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Extra inputs are not permitted" in response.text


def test_run_reconciliation_nested_unknown_field_rejected() -> None:
    payload = _build_valid_payload()
    payload["payments"][0]["random_nested_field"] = "value"
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Extra inputs are not permitted" in response.text


# ── Determinism & Parity Verification ────────────────────────────────────────

def test_run_reconciliation_determinism() -> None:
    payload = _build_valid_payload()

    res1 = client.post("/api/v1/reconciliation/run", json=payload)
    assert res1.status_code == status.HTTP_200_OK

    res2 = client.post("/api/v1/reconciliation/run", json=payload)
    assert res2.status_code == status.HTTP_200_OK

    body1 = res1.json()
    body2 = res2.json()

    # Strip dynamic timestamps
    body1["reconciliation_result"].pop("processed_at", None)
    body2["reconciliation_result"].pop("processed_at", None)

    for card in body1["reconciliation_result"].get("evidence_cards", []):
        card.pop("processed_at", None)
    for card in body2["reconciliation_result"].get("evidence_cards", []):
        card.pop("processed_at", None)

    for exc in body1.get("exceptions", []):
        exc.pop("created_at", None)
    for exc in body2.get("exceptions", []):
        exc.pop("created_at", None)

    # Outputs are identical
    assert body1 == body2


def test_reconcile_batch_api_parity() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)

    # Direct engine run
    service = ReconciliationService()
    direct_result, direct_exceptions = service.reconcile_batch(batch, batch_id="PARITY_TEST")

    # API run
    payload = {
        "merchants": [m.model_dump(mode="json") for m in observed.merchants],
        "payments": [p.model_dump(mode="json") for p in observed.payments],
        "settlements": [s.model_dump(mode="json") for s in observed.settlements],
        "bank_entries": [b.model_dump(mode="json") for b in observed.bank_entries],
        "ledger_entries": [le.model_dump(mode="json") for le in observed.ledger_entries],
        "batch_id": "PARITY_TEST",
    }
    response = client.post("/api/v1/reconciliation/run", json=payload)
    assert response.status_code == status.HTTP_200_OK

    body = response.json()
    api_result = body["reconciliation_result"]
    api_exceptions = body["exceptions"]

    # Assert metric parity
    assert api_result["batch_id"] == direct_result.batch_id
    assert api_result["total_records"] == direct_result.total_records
    assert api_result["auto_matched"] == direct_result.auto_matched
    assert api_result["human_review"] == direct_result.human_review
    assert api_result["abstained"] == direct_result.abstained
    assert Decimal(str(api_result["match_rate"])) == direct_result.match_rate
    assert Decimal(str(api_result["exception_rate"])) == direct_result.exception_rate

    # Assert decision parity
    assert len(api_result["decisions"]) == len(direct_result.decisions)
    for api_dec, direct_dec in zip(api_result["decisions"], direct_result.decisions):
        assert api_dec["payment_id"] == direct_dec.payment_id
        assert api_dec["decision"] == direct_dec.decision
        assert Decimal(str(api_dec["confidence"])) == direct_dec.confidence
        assert api_dec["exception_codes"] == direct_dec.exception_codes

    # Assert exceptions parity
    assert len(api_exceptions) == len(direct_exceptions)
    for api_exc, direct_exc in zip(api_exceptions, direct_exceptions):
        assert api_exc["payment_id"] == direct_exc.payment_id
        assert api_exc["exception_codes"] == direct_exc.exception_codes
        assert api_exc["status"] == direct_exc.status
