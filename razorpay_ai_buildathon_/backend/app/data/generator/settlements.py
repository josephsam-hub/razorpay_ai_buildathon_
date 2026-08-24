"""
LedgerLens Phase 2 — Settlement Factory
=========================================
Groups payments into variable-sized settlement batches (1–5 payments).
Computes gross, fee, and net amounts using Decimal arithmetic only.

RULE: All financial arithmetic uses Decimal — never float.
RULE: fee_amount = round(gross * fee_rate, 2) using ROUND_HALF_UP.
RULE: net_amount = gross - fee_amount (exact Decimal subtraction).
RULE: Batch size is seeded random in [min_batch_size, max_batch_size].
"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.data.generator.config import DatasetConfig
from app.data.generator.models import Merchant, Payment, Settlement

_TWO_PLACES = Decimal("0.01")


def _round_fee(gross: Decimal, fee_rate: Decimal) -> Decimal:
    """Compute fee using ROUND_HALF_UP to match standard banking practice."""
    return (gross * fee_rate).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def make_settlements(
    config: DatasetConfig,
    payments: list[Payment],
    merchants: list[Merchant],
    settlement_seed: int,
    *,
    settlement_ref_start: int = 1,
) -> list[Settlement]:
    """
    Group payments into settlement batches.

    Groups payments by merchant, then batches them in insertion order with a
    seeded variable batch size (1–5 payments per settlement).

    Returns settlements ordered by settlement_date ascending.
    """
    rng = random.Random(settlement_seed)  # noqa: S311

    merchant_map: dict[str, Merchant] = {m.merchant_id: m for m in merchants}

    # Group payments by merchant_id (preserving order)
    merchant_payments: dict[str, list[Payment]] = {}
    for p in payments:
        merchant_payments.setdefault(p.merchant_id, []).append(p)

    settlements: list[Settlement] = []
    ref_counter = settlement_ref_start

    for mid, mpayments in merchant_payments.items():
        merchant = merchant_map[mid]
        idx = 0
        while idx < len(mpayments):
            batch_size = rng.randint(config.min_batch_size, config.max_batch_size)
            batch = mpayments[idx : idx + batch_size]
            idx += batch_size

            # Settlement date = latest payment_date in batch + cycle_days
            latest_payment_date = max(p.payment_date for p in batch)
            settlement_date = latest_payment_date + timedelta(
                days=merchant.settlement_cycle_days
            )

            gross_amount = sum((p.amount for p in batch), Decimal("0"))
            fee_amount = _round_fee(gross_amount, merchant.fee_rate)
            net_amount = gross_amount - fee_amount

            settlement_id_date = settlement_date.strftime("%Y%m%d")
            settlement_id = (
                f"SET_{settlement_id_date}_{ref_counter:04d}"
            )
            settlement_ref = f"REF_SET_{ref_counter:05d}"

            settlement = Settlement(
                settlement_id=settlement_id,
                merchant_id=mid,
                payment_ids=[p.payment_id for p in batch],
                settlement_date=settlement_date,
                gross_amount=gross_amount,
                fee_amount=fee_amount,
                net_amount=net_amount,
                settlement_ref=settlement_ref,
                status="PROCESSED",
            )
            settlements.append(settlement)
            ref_counter += 1

    # Sort by settlement_date for deterministic ordering
    settlements.sort(key=lambda s: s.settlement_date)
    return settlements
