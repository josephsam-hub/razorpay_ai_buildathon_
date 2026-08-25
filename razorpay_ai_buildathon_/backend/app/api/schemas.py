"""
LedgerLens — API Schemas
========================
Defines Pydantic models for API request validation and response serialisation.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.data.generator import models as gen_models
from app.models.decisions import BatchReconciliationResult
from app.models.exceptions import ExceptionRecord


# ── Subclass Generator Models to Enforce Strict Extra-Forbidden Rules ────────

class MerchantSchema(gen_models.Merchant):
    model_config = {"extra": "forbid"}


class PaymentSchema(gen_models.Payment):
    model_config = {"extra": "forbid"}


class SettlementSchema(gen_models.Settlement):
    model_config = {"extra": "forbid"}


class BankEntrySchema(gen_models.BankEntry):
    model_config = {"extra": "forbid"}


class LedgerEntrySchema(gen_models.LedgerEntry):
    model_config = {"extra": "forbid"}


# ── Payload Safety Verification and Float Rejection ─────────────────────────

FORBIDDEN_KEYS = frozenset({
    "ground_truth",
    "corruption_events",
    "applied_seed",
    "corruption_id",
    "original_value",
    "observed_value",
    "corruption_type",
    "target_entity",
    "target_record_id",
})


def check_payload_safety(val: Any) -> None:
    """
    Recursively scans the raw JSON-decoded payload to:
    1. Reject float values (ensuring string/int decimal representations).
    2. Forbid any generator-internal or evaluator-only metadata fields.
    """
    if isinstance(val, float):
        raise ValueError("Float values are not allowed for financial amounts; use strings.")
    elif isinstance(val, dict):
        for k, v in val.items():
            if k in FORBIDDEN_KEYS:
                raise ValueError(f"Forbidden field '{k}' is not allowed in the reconciliation request.")
            check_payload_safety(v)
    elif isinstance(val, list):
        for item in val:
            check_payload_safety(item)


# ── Request / Response Main Models ───────────────────────────────────────────

class ReconciliationRunRequest(BaseModel):
    model_config = {
        "extra": "forbid"
    }

    merchants: list[MerchantSchema] = Field(description="List of Merchant records")
    payments: list[PaymentSchema] = Field(description="List of Payment records")
    settlements: list[SettlementSchema] = Field(description="List of Settlement records")
    bank_entries: list[BankEntrySchema] = Field(description="List of BankEntry records")
    ledger_entries: list[LedgerEntrySchema] = Field(description="List of LedgerEntry records")
    batch_id: Optional[str] = Field(default=None, description="Optional batch identifier")

    @model_validator(mode="before")
    @classmethod
    def validate_payload(cls, data: Any) -> Any:
        check_payload_safety(data)
        return data


class ReconciliationRunResponse(BaseModel):
    """
    Structured output containing the reconciliation decisions and detected exceptions.
    """
    reconciliation_result: BatchReconciliationResult
    exceptions: list[ExceptionRecord]

from app.models.investigation import InvestigationReport

class InvestigationRunRequest(ReconciliationRunRequest):
    """Request contract for investigating one payment in an observed batch."""

    target_payment_id: str = Field(description="Payment ID to investigate")

    @field_validator("target_payment_id")
    @classmethod
    def target_payment_id_not_empty(cls, value: str) -> str:
        if not value or value.strip() == "":
            raise ValueError("target_payment_id cannot be empty or whitespace")
        return value

class InvestigationRunResponse(BaseModel):
    """Deterministic reconciliation output plus the bounded investigation report."""

    deterministic_reconciliation: BatchReconciliationResult
    exceptions: list[ExceptionRecord]
    investigation_report: InvestigationReport
