"""
LedgerLens Phase 3 — Canonical Transaction Model
==================================================
Normalised internal representation produced by the reconciliation normaliser.

One CanonicalTransaction is built per Payment, drawing in any linked
Settlement, BankEntry and LedgerEntry that exist in the ObservedWorld.
Missing linked records are represented as None fields — the engine uses
their absence to detect discrepancies.

RULE: All financial amounts use decimal.Decimal — never float.
RULE: CanonicalTransaction is immutable after construction.
RULE: ObservedWorld entities are never mutated; values are copied here.

ADDED in Fix 3:
  settlement_payment_ids — the full list of payment IDs in the settlement batch.
  Required for the multi-payment gross-amount check (R009).

ADDED in Fix 2/4:
  has_duplicate_bank_entry — populated by the engine when the normaliser
  detects more than one bank entry for this settlement_ref.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class CanonicalTransaction(BaseModel):
    """
    Normalised view of one payment and all related records reachable in
    the ObservedWorld at reconciliation time.

    Fields are grouped by source layer:
      payment_*    — from Payment (always present; anchor)
      settlement_* — from Settlement (None if missing/removed)
      bank_*       — from BankEntry  (None if missing/removed)
      ledger_*     — from LedgerEntry (None if missing/removed)
    """

    model_config = {"frozen": True}

    # ------------------------------------------------------------------
    # Payment layer (anchor — always present)
    # ------------------------------------------------------------------
    payment_id: str = Field(description="PAY_YYYYMMDD_NNNNN — the reconciliation anchor")
    merchant_id: str
    payment_amount: Decimal = Field(description="Payment.amount — never float")
    currency: str
    payment_date: date
    gateway_ref: str

    # ------------------------------------------------------------------
    # Settlement layer (None when settlement is missing for this payment)
    # ------------------------------------------------------------------
    settlement_id: str | None = None
    settlement_ref: str | None = None
    settlement_date: date | None = None
    settlement_gross_amount: Decimal | None = None
    settlement_fee_amount: Decimal | None = None
    settlement_net_amount: Decimal | None = None
    settlement_merchant_id: str | None = None

    # Fix 3: full payment_ids list from the settlement batch.
    # Used to determine whether this is a single-payment or multi-payment
    # settlement, which changes the gross-amount check logic in R009.
    settlement_payment_ids: list[str] = Field(
        default_factory=list,
        description="All payment_ids in the settlement batch (from Settlement.payment_ids). "
                    "Empty when no settlement exists. Required for R009 gross-amount check.",
    )
    latest_payment_date_in_settlement: date | None = None
    settlement_cycle_days: int | None = None


    # Fix 2: flag set by the engine when the normaliser detected multiple bank
    # entries sharing this settlement_ref. Used to emit rec:E003 (duplicate).
    has_duplicate_bank_entry: bool = Field(
        default=False,
        description="True when more than one BankEntry shares this settlement_ref. "
                    "Set by the engine after normalisation.",
    )

    # ------------------------------------------------------------------
    # Bank entry layer (None when bank entry is missing)
    # ------------------------------------------------------------------
    bank_entry_id: str | None = None
    bank_ref: str | None = None
    bank_settlement_ref: str | None = Field(
        default=None,
        description="BankEntry.settlement_ref — must match settlement_ref (clean invariant)",
    )
    bank_credit_amount: Decimal | None = None
    value_date: date | None = None

    # ------------------------------------------------------------------
    # Ledger entry layer (None when ledger entry is missing)
    # ------------------------------------------------------------------
    ledger_entry_id: str | None = None
    ledger_payment_id: str | None = Field(
        default=None,
        description="LedgerEntry.payment_id — must match payment_id (clean invariant)",
    )
    ledger_settlement_id: str | None = None
    ledger_bank_entry_id: str | None = None
    allocated_amount: Decimal | None = None
    posting_date: date | None = None

    # ------------------------------------------------------------------
    # Derived presence flags (convenience)
    # ------------------------------------------------------------------
    @property
    def has_settlement(self) -> bool:
        return self.settlement_id is not None

    @property
    def has_bank_entry(self) -> bool:
        return self.bank_entry_id is not None

    @property
    def has_ledger_entry(self) -> bool:
        return self.ledger_entry_id is not None

    @property
    def is_fully_linked(self) -> bool:
        """True when all four layers (payment/settlement/bank/ledger) are present."""
        return self.has_settlement and self.has_bank_entry and self.has_ledger_entry

    @property
    def is_single_payment_settlement(self) -> bool:
        """True when this payment is the only payment in the settlement batch."""
        return len(self.settlement_payment_ids) == 1
