"""
LedgerLens Phase 2 — Merchant Factory
=======================================
Generates a deterministic list of Merchant entities.

RULE: name and city come from seeded Faker (descriptive only).
RULE: fee_rate and settlement_cycle_days come from config tiers (deterministic).
RULE: merchant_id is seeded ordinal — never Faker.
"""

from __future__ import annotations

import random
from decimal import Decimal

from faker import Faker

from app.data.generator.config import DatasetConfig
from app.data.generator.models import Merchant

# Tier assignment order — cycles through tiers deterministically
_TIER_ORDER = ["T1", "T2", "T3"]


def make_merchants(config: DatasetConfig, merchant_seed: int) -> list[Merchant]:
    """
    Generate n_merchants deterministic Merchant objects.

    Seeds:
      - Faker is seeded with merchant_seed for reproducible names/cities.
      - Tier assignment is round-robin (deterministic, no randomness needed).
    """
    fake = Faker("en_IN")
    fake.seed_instance(merchant_seed)

    # Separate RNG for any future merchant-level numeric randomness
    rng = random.Random(merchant_seed)  # noqa: S311 — not crypto

    merchants: list[Merchant] = []
    for i in range(config.n_merchants):
        tier_key = _TIER_ORDER[i % len(_TIER_ORDER)]
        tier_cfg = config.merchant_tiers[tier_key]

        # Faker — descriptive strings only (Tech Lead Q4 restriction)
        name: str = fake.company()
        city: str = fake.city()

        merchant = Merchant(
            merchant_id=f"M_{i + 1:03d}",
            name=name,
            city=city,
            settlement_tier=tier_key,  # type: ignore[arg-type]
            settlement_cycle_days=tier_cfg.settlement_cycle_days,
            fee_rate=tier_cfg.fee_rate,
            currency=config.currency,
        )
        merchants.append(merchant)

    return merchants
