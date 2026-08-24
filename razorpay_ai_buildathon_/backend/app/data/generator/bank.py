"""
LedgerLens Phase 2 — Bank Entry Factory
=========================================
Generates one BankEntry per Settlement (one credit line per batch).

RULE: credit_amount == settlement.net_amount (clean world invariant).
RULE: value_date = settlement_date + 0 or 1 days (seeded).
RULE: narration is from seeded Faker — descriptive only (Tech Lead Q4).
RULE: bank_ref is seeded — UTR_NNNNN format.
"""

from __future__ import annotations

import random
from datetime import timedelta

from faker import Faker

from app.data.generator.config import DatasetConfig
from app.data.generator.models import BankEntry, Merchant, Settlement


def make_bank_entries(
    config: DatasetConfig,
    settlements: list[Settlement],
    merchants: list[Merchant],
    bank_seed: int,
    *,
    bank_ref_start: int = 10001,
) -> list[BankEntry]:
    """
    Generate one BankEntry per Settlement.

    Seeds:
      - bank_seed controls value_date offset.
      - Faker is seeded with bank_seed for narration strings (descriptive only).
      - bank_ref is sequential from bank_ref_start.
    """
    rng = random.Random(bank_seed)  # noqa: S311
    fake = Faker("en_IN")
    fake.seed_instance(bank_seed)

    merchant_map: dict[str, Merchant] = {m.merchant_id: m for m in merchants}

    bank_entries: list[BankEntry] = []
    for i, settlement in enumerate(settlements):
        merchant = merchant_map[settlement.merchant_id]

        # value_date = settlement_date + 0 or 1 days (seeded)
        value_date_offset = rng.randint(0, 1)
        value_date = settlement.settlement_date + timedelta(days=value_date_offset)

        # Faker — narration is descriptive only (not a financial value)
        narration: str = f"{merchant.name} settlement credit"

        bank_entry = BankEntry(
            bank_entry_id=f"BNK_{value_date.strftime('%Y%m%d')}_{i + 1:04d}",
            merchant_id=settlement.merchant_id,
            settlement_ref=settlement.settlement_ref,
            credit_amount=settlement.net_amount,  # clean world: must equal net_amount
            value_date=value_date,
            bank_ref=f"UTR_{bank_ref_start + i:05d}",
            narration=narration,
        )
        bank_entries.append(bank_entry)

    return bank_entries
