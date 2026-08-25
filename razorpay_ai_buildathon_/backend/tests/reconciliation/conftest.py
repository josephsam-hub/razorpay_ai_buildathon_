"""
Shared fixtures for Phase 3.1 reconciliation tests.

All fixtures build domain objects directly — no file I/O, no database.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.data.generator.models import (
    BankEntry,
    LedgerEntry,
    Merchant,
    Payment,
    Settlement,
)
from app.data.generator.world import ObservedWorld

# ── Fixed test timestamp ──────────────────────────────────────────────────────
FIXED_NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


# ── Primitive builders ────────────────────────────────────────────────────────

def make_merchant(mid: str = "M_001") -> Merchant:
    from decimal import Decimal
    return Merchant(
        merchant_id=mid,
        name="Test Corp",
        city="Mumbai",
        settlement_tier="T1",
        settlement_cycle_days=1,
        fee_rate=Decimal("0.02"),
        currency="INR",
    )


def make_payment(
    pid: str = "PAY_20260801_00001",
    merchant_id: str = "M_001",
    amount: str = "5000.00",
    payment_date: date | None = None,
) -> Payment:
    return Payment(
        payment_id=pid,
        merchant_id=merchant_id,
        amount=Decimal(amount),
        currency="INR",
        payment_date=payment_date or date(2026, 8, 1),
        gateway_ref="RPY_GW_90001",
        status="CAPTURED",
    )


def make_settlement(
    sid: str = "SET_20260802_0001",
    merchant_id: str = "M_001",
    payment_ids: list[str] | None = None,
    gross: str = "5000.00",
    fee: str = "100.00",
    net: str = "4900.00",
    settlement_ref: str = "REF_SET_00001",
    settlement_date: date | None = None,
) -> Settlement:
    return Settlement(
        settlement_id=sid,
        merchant_id=merchant_id,
        payment_ids=payment_ids or ["PAY_20260801_00001"],
        settlement_date=settlement_date or date(2026, 8, 2),
        gross_amount=Decimal(gross),
        fee_amount=Decimal(fee),
        net_amount=Decimal(net),
        settlement_ref=settlement_ref,
    )


def make_bank_entry(
    bid: str = "BNK_20260802_0001",
    merchant_id: str = "M_001",
    settlement_ref: str = "REF_SET_00001",
    credit: str = "4900.00",
    value_date: date | None = None,
    bank_ref: str = "UTR_10001",
) -> BankEntry:
    return BankEntry(
        bank_entry_id=bid,
        merchant_id=merchant_id,
        settlement_ref=settlement_ref,
        credit_amount=Decimal(credit),
        value_date=value_date or date(2026, 8, 2),
        bank_ref=bank_ref,
        narration="Test Corp settlement credit",
    )


def make_ledger_entry(
    lid: str = "LED_20260802_0001",
    merchant_id: str = "M_001",
    payment_id: str = "PAY_20260801_00001",
    settlement_id: str = "SET_20260802_0001",
    bank_entry_id: str = "BNK_20260802_0001",
    allocated: str = "4900.00",
    posting_date: date | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        ledger_entry_id=lid,
        merchant_id=merchant_id,
        payment_id=payment_id,
        settlement_id=settlement_id,
        bank_entry_id=bank_entry_id,
        allocated_amount=Decimal(allocated),
        posting_date=posting_date or date(2026, 8, 2),
    )


def make_clean_world(
    payment_id: str = "PAY_20260801_00001",
    merchant_id: str = "M_001",
    settlement_ref: str = "REF_SET_00001",
) -> ObservedWorld:
    """A minimal fully-linked ObservedWorld with one clean payment."""
    merchant = make_merchant(merchant_id)
    payment = make_payment(payment_id, merchant_id)
    settlement = make_settlement(
        payment_ids=[payment_id],
        merchant_id=merchant_id,
        settlement_ref=settlement_ref,
    )
    bank = make_bank_entry(
        merchant_id=merchant_id,
        settlement_ref=settlement_ref,
    )
    ledger = make_ledger_entry(
        merchant_id=merchant_id,
        payment_id=payment_id,
        settlement_id=settlement.settlement_id,
        bank_entry_id=bank.bank_entry_id,
    )
    return ObservedWorld(
        merchants=[merchant],
        payments=[payment],
        settlements=[settlement],
        bank_entries=[bank],
        ledger_entries=[ledger],
        ground_truth=[],
        corruption_events=[],
    )


# ── Pytest fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def clean_world() -> ObservedWorld:
    return make_clean_world()


@pytest.fixture
def fixed_now() -> datetime:
    return FIXED_NOW
