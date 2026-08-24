"""
LedgerLens Phase 2 — Payment Factory
======================================
Generates a deterministic list of Payment entities.

RULE: All financial values (amount) come from seeded RNG — never Faker.
RULE: payment_date is seeded deterministic within config date range.
RULE: gateway_ref is seeded — RPY_GW_NNNNN format.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from app.data.generator.config import DatasetConfig
from app.data.generator.models import Merchant, Payment


def _random_amount(rng: random.Random, cfg_min: Decimal, cfg_max: Decimal) -> Decimal:
    """
    Return a Decimal amount in [cfg_min, cfg_max] with 2 decimal places.
    Uses integer arithmetic to avoid float precision errors.
    """
    min_paisa = int(cfg_min * 100)
    max_paisa = int(cfg_max * 100)
    paisa = rng.randint(min_paisa, max_paisa)
    return Decimal(paisa) / Decimal(100)


def _random_date(rng: random.Random, start: date, end: date) -> date:
    """Return a uniformly random date in [start, end]."""
    delta = (end - start).days
    return start + timedelta(days=rng.randint(0, delta))


def make_payments(
    config: DatasetConfig,
    merchants: list[Merchant],
    payment_seed: int,
    *,
    gateway_ref_start: int = 90001,
) -> list[Payment]:
    """
    Generate n_payments deterministic Payment objects.

    Payments are distributed across merchants proportionally (round-robin).

    Seeds:
      - payment_seed controls all amount and date generation.
      - gateway_ref is a sequential counter starting from gateway_ref_start.
    """
    rng = random.Random(payment_seed)  # noqa: S311

    start_date = date.fromisoformat(config.start_date)
    end_date = date.fromisoformat(config.end_date)

    merchant_cycle = [m for m in merchants]
    payments: list[Payment] = []

    for i in range(config.n_payments):
        merchant = merchant_cycle[i % len(merchant_cycle)]
        pdate = _random_date(rng, start_date, end_date)
        amount = _random_amount(
            rng,
            config.payment_amount.min_amount,
            config.payment_amount.max_amount,
        )

        payment = Payment(
            payment_id=f"PAY_{pdate.strftime('%Y%m%d')}_{i + 1:05d}",
            merchant_id=merchant.merchant_id,
            amount=amount,
            currency=config.currency,
            payment_date=pdate,
            gateway_ref=f"RPY_GW_{gateway_ref_start + i:05d}",
            status="CAPTURED",
        )
        payments.append(payment)

    return payments
