"""
LedgerLens — ReconciliationBatch Input Abstraction
==================================================
Defines the clean domain boundary for inputs passed to the reconciliation engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from app.data.generator.models import (
    BankEntry,
    LedgerEntry,
    Merchant,
    Payment,
    Settlement,
)

if TYPE_CHECKING:
    from app.data.generator.world import ObservedWorld


@dataclass(frozen=True)
class ReconciliationBatch:
    """
    Domain container for observed financial records.
    Explicitly decoupled from generator-specific evaluation data.
    """
    payments: tuple[Payment, ...]
    settlements: tuple[Settlement, ...]
    bank_entries: tuple[BankEntry, ...]
    ledger_entries: tuple[LedgerEntry, ...]
    merchants: tuple[Merchant, ...]
    batch_id: str = ""

    def __post_init__(self) -> None:
        # Guarantee Decimal values for all payments
        for p in self.payments:
            if not isinstance(p.amount, Decimal):
                raise TypeError(f"Payment {p.payment_id} amount must be Decimal, got {type(p.amount)}")


def from_observed_world(observed: ObservedWorld) -> ReconciliationBatch:
    """
    Adapts legacy generator ObservedWorld to ReconciliationBatch.
    Strips ground truth and corruption events.
    """
    return ReconciliationBatch(
        payments=tuple(observed.payments),
        settlements=tuple(observed.settlements),
        bank_entries=tuple(observed.bank_entries),
        ledger_entries=tuple(observed.ledger_entries),
        merchants=tuple(observed.merchants),
    )
