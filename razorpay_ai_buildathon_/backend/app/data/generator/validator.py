"""
LedgerLens Phase 2 — Dataset Integrity Validator
==================================================
10 invariants checked on the clean world after generation.

Invariants:
  INV-01  All payment_ids are unique
  INV-02  All settlement_ids are unique
  INV-03  All bank_entry_ids are unique (clean world)
  INV-04  All ledger_entry_ids are unique
  INV-05  Every settlement.payment_id references a known payment
  INV-06  Every bank_entry.settlement_ref references a known settlement
  INV-07  Every ledger_entry.payment_id references a known payment
  INV-08  settlement.gross_amount == sum(payment.amount for batch)
  INV-09  settlement.gross - fee == net (exact Decimal)
  INV-10  sum(ledger.allocated_amount per batch) == settlement.net_amount
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.data.generator.models import (
    BankEntry,
    LedgerEntry,
    Merchant,
    Payment,
    Settlement,
)


@dataclass
class ValidationResult:
    """Result of running DatasetIntegrityValidator."""

    passed: bool
    violations: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.passed:
            return "PASS — all 10 invariants satisfied"
        return f"FAIL — {len(self.violations)} violation(s):\n" + "\n".join(
            f"  • {v}" for v in self.violations
        )


class DatasetIntegrityValidator:
    """Runs all 10 invariants on a clean world snapshot."""

    def validate(
        self,
        merchants: list[Merchant],
        payments: list[Payment],
        settlements: list[Settlement],
        bank_entries: list[BankEntry],
        ledger_entries: list[LedgerEntry],
    ) -> ValidationResult:
        violations: list[str] = []

        payment_map = {p.payment_id: p for p in payments}
        settlement_map = {s.settlement_id: s for s in settlements}
        settlement_ref_map = {s.settlement_ref: s for s in settlements}

        # INV-01: Unique payment_ids
        if len(payment_map) != len(payments):
            violations.append(
                f"INV-01: Duplicate payment_ids found "
                f"({len(payments) - len(payment_map)} duplicates)"
            )

        # INV-02: Unique settlement_ids
        if len(settlement_map) != len(settlements):
            violations.append(
                f"INV-02: Duplicate settlement_ids found "
                f"({len(settlements) - len(settlement_map)} duplicates)"
            )

        # INV-03: Unique bank_entry_ids
        bank_id_set = {b.bank_entry_id for b in bank_entries}
        if len(bank_id_set) != len(bank_entries):
            violations.append(
                f"INV-03: Duplicate bank_entry_ids found "
                f"({len(bank_entries) - len(bank_id_set)} duplicates)"
            )

        # INV-04: Unique ledger_entry_ids
        ledger_id_set = {le.ledger_entry_id for le in ledger_entries}
        if len(ledger_id_set) != len(ledger_entries):
            violations.append(
                f"INV-04: Duplicate ledger_entry_ids found "
                f"({len(ledger_entries) - len(ledger_id_set)} duplicates)"
            )

        # INV-05: Settlement payment_ids reference known payments
        for s in settlements:
            for pid in s.payment_ids:
                if pid not in payment_map:
                    violations.append(
                        f"INV-05: Settlement {s.settlement_id} references "
                        f"unknown payment_id '{pid}'"
                    )

        # INV-06: BankEntry.settlement_ref references known settlement
        for b in bank_entries:
            if b.settlement_ref not in settlement_ref_map:
                violations.append(
                    f"INV-06: BankEntry {b.bank_entry_id} references "
                    f"unknown settlement_ref '{b.settlement_ref}'"
                )

        # INV-07: LedgerEntry.payment_id references known payment
        for le in ledger_entries:
            if le.payment_id not in payment_map:
                violations.append(
                    f"INV-07: LedgerEntry {le.ledger_entry_id} references "
                    f"unknown payment_id '{le.payment_id}'"
                )

        # INV-08: settlement.gross_amount == sum(batch payment amounts)
        for s in settlements:
            batch_sum = sum(
                (payment_map[pid].amount for pid in s.payment_ids if pid in payment_map),
                Decimal("0"),
            )
            if batch_sum != s.gross_amount:
                violations.append(
                    f"INV-08: Settlement {s.settlement_id} gross_amount "
                    f"{s.gross_amount} != sum of payments {batch_sum}"
                )

        # INV-09: gross - fee == net (exact)
        for s in settlements:
            expected_net = s.gross_amount - s.fee_amount
            if expected_net != s.net_amount:
                violations.append(
                    f"INV-09: Settlement {s.settlement_id} "
                    f"gross({s.gross_amount}) - fee({s.fee_amount}) "
                    f"= {expected_net} != net({s.net_amount})"
                )

        # INV-10: sum(ledger.allocated_amount per batch) == settlement.net_amount
        settlement_to_ledgers: dict[str, list[LedgerEntry]] = {}
        for le in ledger_entries:
            settlement_to_ledgers.setdefault(le.settlement_id, []).append(le)

        for s in settlements:
            batch_ledgers = settlement_to_ledgers.get(s.settlement_id, [])
            if not batch_ledgers:
                # No ledger entries for this settlement — may be valid if bank missing
                continue
            allocated_sum = sum(
                (le.allocated_amount for le in batch_ledgers), Decimal("0")
            )
            if allocated_sum != s.net_amount:
                violations.append(
                    f"INV-10: Settlement {s.settlement_id} "
                    f"sum(allocated_amount)={allocated_sum} "
                    f"!= net_amount={s.net_amount}"
                )

        return ValidationResult(passed=len(violations) == 0, violations=violations)
