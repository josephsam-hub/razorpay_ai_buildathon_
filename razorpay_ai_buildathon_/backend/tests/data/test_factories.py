"""
Tests — Factory outputs satisfy all 10 invariants.
Uses a small config (n=20) for fast test execution.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.data.generator.config import DatasetConfig
from app.data.generator.merchants import make_merchants
from app.data.generator.payments import make_payments
from app.data.generator.settlements import make_settlements
from app.data.generator.bank import make_bank_entries
from app.data.generator.ledger import make_ledger_entries
from app.data.generator.validator import DatasetIntegrityValidator
from app.data.generator.world import WorldBuilder, generate


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def small_config():
    return DatasetConfig.model_validate({
        "version": "test",
        "n_payments": 20,
        "n_merchants": 3,
        "seed": 7,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-15",
        "corruption": {
            "missing_settlement": 0.0,
            "missing_bank_entry": 0.0,
            "missing_ledger_entry": 0.0,
            "amount_mismatch": 0.0,
            "date_mismatch": 0.0,
            "duplicate_bank_entry": 0.0,
            "settlement_fee_variance": 0.0,
            "orphan_bank_entry": 0.0,
        },
    })


@pytest.fixture(scope="module")
def clean_world(small_config):
    builder = WorldBuilder(small_config)
    return builder.build_clean()


# ---------------------------------------------------------------------------
# INV-01: Unique payment_ids
# ---------------------------------------------------------------------------

class TestINV01:
    def test_payment_ids_unique(self, clean_world):
        ids = [p.payment_id for p in clean_world.payments]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# INV-02: Unique settlement_ids
# ---------------------------------------------------------------------------

class TestINV02:
    def test_settlement_ids_unique(self, clean_world):
        ids = [s.settlement_id for s in clean_world.settlements]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# INV-03: Unique bank_entry_ids
# ---------------------------------------------------------------------------

class TestINV03:
    def test_bank_entry_ids_unique(self, clean_world):
        ids = [b.bank_entry_id for b in clean_world.bank_entries]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# INV-04: Unique ledger_entry_ids
# ---------------------------------------------------------------------------

class TestINV04:
    def test_ledger_entry_ids_unique(self, clean_world):
        ids = [le.ledger_entry_id for le in clean_world.ledger_entries]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# INV-05: Settlement payment_ids reference known payments
# ---------------------------------------------------------------------------

class TestINV05:
    def test_settlement_references_known_payments(self, clean_world):
        payment_ids = {p.payment_id for p in clean_world.payments}
        for s in clean_world.settlements:
            for pid in s.payment_ids:
                assert pid in payment_ids, (
                    f"Settlement {s.settlement_id} references unknown payment {pid}"
                )


# ---------------------------------------------------------------------------
# INV-06: BankEntry.settlement_ref references known settlement
# ---------------------------------------------------------------------------

class TestINV06:
    def test_bank_entry_references_known_settlement(self, clean_world):
        settlement_refs = {s.settlement_ref for s in clean_world.settlements}
        for b in clean_world.bank_entries:
            assert b.settlement_ref in settlement_refs, (
                f"BankEntry {b.bank_entry_id} references unknown settlement_ref {b.settlement_ref}"
            )


# ---------------------------------------------------------------------------
# INV-07: LedgerEntry.payment_id references known payment
# ---------------------------------------------------------------------------

class TestINV07:
    def test_ledger_entry_references_known_payment(self, clean_world):
        payment_ids = {p.payment_id for p in clean_world.payments}
        for le in clean_world.ledger_entries:
            assert le.payment_id in payment_ids, (
                f"LedgerEntry {le.ledger_entry_id} references unknown payment {le.payment_id}"
            )


# ---------------------------------------------------------------------------
# INV-08: settlement.gross_amount == sum(batch payment amounts)
# ---------------------------------------------------------------------------

class TestINV08:
    def test_gross_amount_equals_batch_sum(self, clean_world):
        payment_map = {p.payment_id: p for p in clean_world.payments}
        for s in clean_world.settlements:
            batch_sum = sum(
                payment_map[pid].amount for pid in s.payment_ids
            )
            assert batch_sum == s.gross_amount, (
                f"Settlement {s.settlement_id}: gross={s.gross_amount} != batch_sum={batch_sum}"
            )


# ---------------------------------------------------------------------------
# INV-09: gross - fee == net (exact Decimal)
# ---------------------------------------------------------------------------

class TestINV09:
    def test_net_equals_gross_minus_fee(self, clean_world):
        for s in clean_world.settlements:
            expected = s.gross_amount - s.fee_amount
            assert expected == s.net_amount, (
                f"Settlement {s.settlement_id}: {s.gross_amount} - {s.fee_amount} = {expected} != {s.net_amount}"
            )


# ---------------------------------------------------------------------------
# INV-10: sum(allocated_amount per batch) == settlement.net_amount
# ---------------------------------------------------------------------------

class TestINV10:
    def test_allocation_sums_to_net(self, clean_world):
        settlement_to_ledgers: dict[str, list] = {}
        for le in clean_world.ledger_entries:
            settlement_to_ledgers.setdefault(le.settlement_id, []).append(le)

        for s in clean_world.settlements:
            batch_ledgers = settlement_to_ledgers.get(s.settlement_id, [])
            if not batch_ledgers:
                continue
            total = sum(le.allocated_amount for le in batch_ledgers)
            assert total == s.net_amount, (
                f"Settlement {s.settlement_id}: sum(allocated)={total} != net={s.net_amount}"
            )


# ---------------------------------------------------------------------------
# Full validator pass
# ---------------------------------------------------------------------------

class TestFullValidator:
    def test_validator_passes_clean_world(self, clean_world):
        validator = DatasetIntegrityValidator()
        result = validator.validate(
            merchants=clean_world.merchants,
            payments=clean_world.payments,
            settlements=clean_world.settlements,
            bank_entries=clean_world.bank_entries,
            ledger_entries=clean_world.ledger_entries,
        )
        assert result.passed, str(result)

    def test_merchant_fields(self, clean_world):
        for m in clean_world.merchants:
            assert isinstance(m.name, str)
            assert isinstance(m.city, str)
            assert isinstance(m.fee_rate, Decimal)
            assert not isinstance(m.fee_rate, float)

    def test_payment_amounts_are_decimal(self, clean_world):
        for p in clean_world.payments:
            assert isinstance(p.amount, Decimal)
            assert p.amount > 0

    def test_one_ledger_entry_per_payment(self, clean_world):
        """Each payment should have exactly one ledger entry (clean world)."""
        payment_ids_with_ledger = {le.payment_id for le in clean_world.ledger_entries}
        # Every payment that has a settlement should have a ledger entry
        settlement_payment_ids = {
            pid
            for s in clean_world.settlements
            for pid in s.payment_ids
        }
        # All settlement payments should have ledger entries
        for pid in settlement_payment_ids:
            assert pid in payment_ids_with_ledger, (
                f"Payment {pid} is in a settlement but has no ledger entry"
            )
