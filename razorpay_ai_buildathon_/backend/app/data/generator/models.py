"""
LedgerLens Phase 2 — Domain Models
===================================
All 8 Pydantic models for the synthetic financial world.

RULE: All financial amounts use decimal.Decimal — never float.
RULE: Faker is only used for descriptive string fields (name, city, narration).
RULE: Clean truth is never mutated after construction.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Entity 1 — Merchant
# ---------------------------------------------------------------------------

class Merchant(BaseModel):
    """Reference entity. Drives settlement cycle and fee rate."""

    merchant_id: str = Field(description="M_001 … M_NNN")
    name: str = Field(description="Faker descriptive — not a financial value")
    city: str = Field(description="Faker descriptive — not a financial value")
    settlement_tier: Literal["T1", "T2", "T3"]
    settlement_cycle_days: int = Field(ge=1, le=3)
    fee_rate: Decimal = Field(description="Deterministic seeded — never Faker")
    currency: str = "INR"

    @field_validator("fee_rate")
    @classmethod
    def fee_rate_in_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0.001") <= v <= Decimal("0.05")):
            raise ValueError(f"fee_rate {v} outside [0.001, 0.05]")
        return v


# ---------------------------------------------------------------------------
# Entity 2 — Payment
# ---------------------------------------------------------------------------

class Payment(BaseModel):
    """Source of truth for a single captured payment."""

    payment_id: str = Field(description="PAY_YYYYMMDD_NNNN")
    merchant_id: str
    amount: Decimal = Field(description="Deterministic seeded — never Faker")
    currency: str = "INR"
    payment_date: date
    gateway_ref: str = Field(description="RPY_GW_NNNNN — seeded")
    status: Literal["CAPTURED", "REFUNDED", "FAILED"] = "CAPTURED"

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError(f"Payment amount must be positive, got {v}")
        return v


# ---------------------------------------------------------------------------
# Entity 3 — Settlement
# ---------------------------------------------------------------------------

class Settlement(BaseModel):
    """Batch settlement covering 1–5 payments for a single merchant."""

    settlement_id: str = Field(description="SET_YYYYMMDD_NNNN")
    merchant_id: str
    payment_ids: list[str] = Field(min_length=1, max_length=5)
    settlement_date: date
    gross_amount: Decimal = Field(description="sum(payment.amount)")
    fee_amount: Decimal = Field(description="round(gross * fee_rate, 2)")
    net_amount: Decimal = Field(description="gross - fee")
    settlement_ref: str = Field(description="REF_SET_NNNNN — seeded")
    status: Literal["INITIATED", "PROCESSED", "FAILED"] = "PROCESSED"

    @model_validator(mode="after")
    def validate_amounts(self) -> "Settlement":
        expected_net = self.gross_amount - self.fee_amount
        if expected_net != self.net_amount:
            raise ValueError(
                f"net_amount {self.net_amount} != gross {self.gross_amount}"
                f" - fee {self.fee_amount} = {expected_net}"
            )
        if self.gross_amount <= 0:
            raise ValueError("gross_amount must be positive")
        if self.fee_amount < 0:
            raise ValueError("fee_amount must be non-negative")
        return self


# ---------------------------------------------------------------------------
# Entity 4 — Bank Entry
# ---------------------------------------------------------------------------

class BankEntry(BaseModel):
    """Single credit line in the merchant's bank statement (one per settlement batch)."""

    bank_entry_id: str = Field(description="BNK_YYYYMMDD_NNNN")
    merchant_id: str
    settlement_ref: str = Field(description="matches settlement.settlement_ref")
    credit_amount: Decimal = Field(description="== settlement.net_amount (clean)")
    value_date: date
    bank_ref: str = Field(description="UTR_NNNNN — seeded")
    narration: str = Field(description="Faker descriptive — not a financial value")

    @field_validator("credit_amount")
    @classmethod
    def credit_amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError(f"Bank credit_amount must be positive, got {v}")
        return v


# ---------------------------------------------------------------------------
# Entity 5 — Ledger Entry
# ---------------------------------------------------------------------------

class LedgerEntry(BaseModel):
    """
    Double-entry record in the merchant's ERP.
    ONE ROW PER PAYMENT (per-payment allocation, Tech Lead Q1 decision).
    """

    ledger_entry_id: str = Field(description="LED_YYYYMMDD_NNNN")
    merchant_id: str
    payment_id: str = Field(description="one-to-one with Payment")
    settlement_id: str
    bank_entry_id: str
    allocated_amount: Decimal = Field(
        description="payment's pro-rata share of settlement.net_amount"
    )
    posting_date: date
    account_code: str = "1000-PAYMENTS-RECEIVED"
    status: Literal["DRAFT", "POSTED", "RECONCILED"] = "POSTED"
    reconciled_flag: bool = False

    @field_validator("allocated_amount")
    @classmethod
    def allocated_amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError(f"allocated_amount must be positive, got {v}")
        return v


# ---------------------------------------------------------------------------
# Entity 6 — Corruption Event
# ---------------------------------------------------------------------------

class CorruptionEvent(BaseModel):
    """
    Explicit log of a single corruption applied during generation.
    Used by the evaluator only — never loaded by the reconciliation engine.
    """

    corruption_id: str = Field(description="CE_YYYYMMDD_NNNN")
    case_id: str = Field(description="FK -> payment_id (the anchor case)")
    corruption_type: str = Field(description="E001-E008 name e.g. amount_mismatch")
    target_entity: str = Field(description="settlement / bank_entry / ledger_entry")
    target_record_id: str = Field(description="the specific record ID modified/removed")
    original_value: str = Field(
        description="JSON of original field/state or '<row_present>'"
    )
    observed_value: str = Field(
        description="JSON of post-corruption field/state or '<row_removed>'"
    )
    delta: str | None = Field(
        default=None,
        description="numeric delta string e.g. '-50.00' for amount mismatches",
    )
    applied_seed: int = Field(description="corrupt_op_seed used for this event")


# ---------------------------------------------------------------------------
# Entity 7 — Ground Truth
# ---------------------------------------------------------------------------

class GroundTruth(BaseModel):
    """
    Expected evaluation outcome per payment.
    One row per payment — independent from observed data.
    Never loaded by the reconciliation engine.
    """

    ground_truth_id: str = Field(description="GT_YYYYMMDD_NNNN")
    payment_id: str = Field(description="one row per payment")
    expected_decision: Literal["AUTO_MATCH", "HUMAN_REVIEW", "ABSTAIN"]
    discrepancy_type: str | None = None
    discrepancy_code: str | None = Field(
        default=None, description="E001-E008"
    )
    corruption_id: str | None = Field(
        default=None, description="FK -> CorruptionEvent (null for clean cases)"
    )
    injected_layer: str | None = Field(
        default=None,
        description=(
            "Canonical layer name: 'payment', 'settlement', 'bank', or 'ledger'. "
            "Maps from target_entity: settlement -> settlement, bank_entry -> bank, ledger_entry -> ledger."
        ),
    )
    clean_settlement_net_amount: Decimal | None = Field(
        default=None,
        description=(
            "Settlement-level: clean truth net_amount for the parent settlement batch. "
            "Useful for detecting fee/net discrepancies (E007)."
        ),
    )
    clean_allocated_amount: Decimal | None = Field(
        default=None,
        description=(
            "Payment-level: clean truth per-payment allocated_amount from the ledger. "
            "Useful for detecting bank/ledger allocation mismatches."
        ),
    )
    notes: str = ""


# ---------------------------------------------------------------------------
# Entity 8 — Dataset Metadata
# ---------------------------------------------------------------------------

class DatasetMetadata(BaseModel):
    """
    Reproducibility and audit metadata for a generated dataset.
    Serialised to metadata.json alongside CSV outputs.
    """

    dataset_version: str = Field(description="from config.version")
    generator_version: str = Field(description="from app.__version__")
    seed: int
    currency: str = "INR"
    generation_timestamp: datetime
    record_counts: dict[str, int] = Field(
        description="table -> row count"
    )
    corruption_profile: dict[str, int] = Field(
        description="discrepancy_type -> actual count applied"
    )
    config_hash: str = Field(description="sha256 of the config YAML file")
    file_hashes: dict[str, str] = Field(description="filename -> sha256")
