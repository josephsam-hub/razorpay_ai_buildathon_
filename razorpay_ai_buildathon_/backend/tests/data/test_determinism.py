"""
Tests — Determinism: same seed produces identical output; different seed differs.
"""

from __future__ import annotations

import pytest

from app.data.generator.config import DatasetConfig
from app.data.generator.world import WorldBuilder, generate


def _config(seed: int, n: int = 20) -> DatasetConfig:
    return DatasetConfig.model_validate({
        "version": "test",
        "n_payments": n,
        "n_merchants": 3,
        "seed": seed,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "corruption": {
            "missing_settlement": 0.1,
            "missing_bank_entry": 0.1,
            "amount_mismatch": 0.05,
            "date_mismatch": 0.05,
            "duplicate_bank_entry": 0.0,
            "settlement_fee_variance": 0.0,
            "orphan_bank_entry": 0.0,
            "missing_ledger_entry": 0.0,
        },
    })


class TestSameSeedIdenticalOutput:
    """CRITICAL: same seed must produce byte-identical results."""

    def test_payments_identical(self):
        a, _ = generate(_config(seed=42))
        b, _ = generate(_config(seed=42))
        assert [(p.payment_id, str(p.amount), p.payment_date.isoformat())
                for p in a.payments] == \
               [(p.payment_id, str(p.amount), p.payment_date.isoformat())
                for p in b.payments]

    def test_settlements_identical(self):
        a, _ = generate(_config(seed=42))
        b, _ = generate(_config(seed=42))
        assert [(s.settlement_id, str(s.net_amount)) for s in a.settlements] == \
               [(s.settlement_id, str(s.net_amount)) for s in b.settlements]

    def test_bank_entries_identical(self):
        a, _ = generate(_config(seed=42))
        b, _ = generate(_config(seed=42))
        assert [be.bank_entry_id for be in a.bank_entries] == \
               [be.bank_entry_id for be in b.bank_entries]

    def test_ledger_entries_identical(self):
        a, _ = generate(_config(seed=42))
        b, _ = generate(_config(seed=42))
        assert [(le.ledger_entry_id, str(le.allocated_amount)) for le in a.ledger_entries] == \
               [(le.ledger_entry_id, str(le.allocated_amount)) for le in b.ledger_entries]

    def test_ground_truth_identical(self):
        _, obs_a = generate(_config(seed=42))
        _, obs_b = generate(_config(seed=42))
        assert [(gt.payment_id, gt.expected_decision, gt.discrepancy_type)
                for gt in obs_a.ground_truth] == \
               [(gt.payment_id, gt.expected_decision, gt.discrepancy_type)
                for gt in obs_b.ground_truth]

    def test_corruption_events_identical(self):
        _, obs_a = generate(_config(seed=42))
        _, obs_b = generate(_config(seed=42))
        assert [(ce.corruption_id, ce.corruption_type, ce.delta)
                for ce in obs_a.corruption_events] == \
               [(ce.corruption_id, ce.corruption_type, ce.delta)
                for ce in obs_b.corruption_events]

    def test_merchant_names_identical(self):
        a, _ = generate(_config(seed=42))
        b, _ = generate(_config(seed=42))
        assert [m.name for m in a.merchants] == [m.name for m in b.merchants]
        assert [m.city for m in a.merchants] == [m.city for m in b.merchants]


class TestDifferentSeedDiffersOutput:
    """Different seeds must produce different datasets."""

    def test_payment_amounts_differ(self):
        a, _ = generate(_config(seed=42))
        b, _ = generate(_config(seed=99))
        amounts_a = [str(p.amount) for p in a.payments]
        amounts_b = [str(p.amount) for p in b.payments]
        assert amounts_a != amounts_b, "Different seeds should produce different payment amounts"

    def test_settlement_nets_differ(self):
        a, _ = generate(_config(seed=42))
        b, _ = generate(_config(seed=99))
        nets_a = [str(s.net_amount) for s in a.settlements]
        nets_b = [str(s.net_amount) for s in b.settlements]
        assert nets_a != nets_b, "Different seeds should produce different settlement nets"

    def test_corruption_patterns_differ(self):
        _, obs_a = generate(_config(seed=42))
        _, obs_b = generate(_config(seed=99))
        types_a = [gt.expected_decision for gt in obs_a.ground_truth]
        types_b = [gt.expected_decision for gt in obs_b.ground_truth]
        assert types_a != types_b, "Different seeds should produce different corruption patterns"


class TestSeedDerivation:
    """Verify that sub-seeds are derived independently."""

    def test_merchant_seed_differs_from_payment_seed(self):
        """Sub-seeds must be different for each stream."""
        from app.data.generator.world import _derive_seed
        master = 42
        merchant_seed = _derive_seed(master, 1)
        payment_seed = _derive_seed(master, 2)
        settlement_seed = _derive_seed(master, 3)
        bank_seed = _derive_seed(master, 4)
        ledger_seed = _derive_seed(master, 5)
        corrupt_seed = _derive_seed(master, 6)

        seeds = {merchant_seed, payment_seed, settlement_seed,
                 bank_seed, ledger_seed, corrupt_seed}
        # All 6 seeds should be distinct
        assert len(seeds) == 6, f"Seed collision detected: {seeds}"
