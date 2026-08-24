"""
LedgerLens Phase 2 — Ledger Entry Factory
===========================================
Generates ONE LedgerEntry per Payment (per-payment allocation).

ALLOCATION ALGORITHM (Tech Lead Q1 decision):
  For a settlement batch with N payments [p_0 ... p_{N-1}]:
    For i in 0..N-2:
      allocated_amount[i] = round(p_i.amount / settlement.gross_amount
                                  * settlement.net_amount, 2)  [ROUND_HALF_UP]
    For i = N-1 (last payment):
      allocated_amount[N-1] = settlement.net_amount - sum(allocated_amount[0..N-2])

  INVARIANT: sum(allocated_amount for batch) == settlement.net_amount exactly.
  The last-payment-gets-remainder pattern eliminates cumulative rounding error.

RULE: posting_date = bank_entry.value_date + 0, 1, or 2 days (seeded).
RULE: All arithmetic uses Decimal — never float.
"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.data.generator.config import DatasetConfig
from app.data.generator.models import BankEntry, LedgerEntry, Payment, Settlement

_TWO_PLACES = Decimal("0.01")


def _allocate(
    payments: list[Payment],
    settlement: Settlement,
) -> list[Decimal]:
    """
    Compute per-payment allocated_amount list.

    Returns a list of Decimal values such that:
      sum(result) == settlement.net_amount  (exactly)
    """
    n = len(payments)
    if n == 0:
        return []

    net = settlement.net_amount
    gross = settlement.gross_amount

    if n == 1:
        return [net]

    allocations: list[Decimal] = []
    running_sum = Decimal("0")

    for i, payment in enumerate(payments[:-1]):
        share = (payment.amount / gross * net).quantize(
            _TWO_PLACES, rounding=ROUND_HALF_UP
        )
        allocations.append(share)
        running_sum += share

    # Last payment gets the remainder — eliminates rounding error
    last_allocation = net - running_sum
    allocations.append(last_allocation)

    return allocations


def make_ledger_entries(
    config: DatasetConfig,
    payments: list[Payment],
    settlements: list[Settlement],
    bank_entries: list[BankEntry],
    ledger_seed: int,
) -> list[LedgerEntry]:
    """
    Generate one LedgerEntry per Payment.

    Maps each settlement batch to its bank entry, then allocates
    the net_amount across the batch payments using the approved algorithm.
    """
    rng = random.Random(ledger_seed)  # noqa: S311

    # Build lookup maps
    payment_map: dict[str, Payment] = {p.payment_id: p for p in payments}
    bank_by_settlement_ref: dict[str, BankEntry] = {
        b.settlement_ref: b for b in bank_entries
    }

    ledger_entries: list[LedgerEntry] = []
    entry_counter = 1

    for settlement in settlements:
        bank_entry = bank_by_settlement_ref.get(settlement.settlement_ref)
        if bank_entry is None:
            # No bank entry for this settlement (may occur after corruption)
            # Skip ledger creation for missing bank entries
            continue

        batch_payments = [
            payment_map[pid]
            for pid in settlement.payment_ids
            if pid in payment_map
        ]
        if not batch_payments:
            continue

        allocated_amounts = _allocate(batch_payments, settlement)

        for payment, allocated_amount in zip(batch_payments, allocated_amounts):
            # posting_date = value_date + 0, 1, or 2 days (seeded)
            posting_offset = rng.randint(0, 2)
            posting_date = bank_entry.value_date + timedelta(days=posting_offset)

            ledger_date_str = posting_date.strftime("%Y%m%d")
            ledger_entry = LedgerEntry(
                ledger_entry_id=f"LED_{ledger_date_str}_{entry_counter:04d}",
                merchant_id=settlement.merchant_id,
                payment_id=payment.payment_id,
                settlement_id=settlement.settlement_id,
                bank_entry_id=bank_entry.bank_entry_id,
                allocated_amount=allocated_amount,
                posting_date=posting_date,
                account_code="1000-PAYMENTS-RECEIVED",
                status="POSTED",
                reconciled_flag=False,
            )
            ledger_entries.append(ledger_entry)
            entry_counter += 1

    return ledger_entries
