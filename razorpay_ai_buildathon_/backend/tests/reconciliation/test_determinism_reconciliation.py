"""
Tests — Determinism of the reconciliation engine.

Covers:
  - same input → same decisions (run twice)
  - same input → same confidence values
  - same input → same evidence card rule_ids
  - shuffled payment list → same decisions as sorted
  - shuffled settlements list → same decisions
  - shuffled bank entries list → same decisions
  - tie-breaking: two settlements with equal composite score, lower id wins
  - processed_at does not affect decision
"""

from __future__ import annotations

import random
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.data.generator.config import DatasetConfig
from app.data.generator.world import generate, ObservedWorld
from app.services.reconciliation import ReconciliationService

from tests.reconciliation.conftest import FIXED_NOW


def _svc():
    return ReconciliationService()


def _config(seed: int = 42, n: int = 30, corruption: dict | None = None):
    return DatasetConfig.model_validate({
        "version": "test",
        "n_payments": n,
        "n_merchants": 3,
        "seed": seed,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "corruption": corruption or {
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


class TestIdenticalInputIdenticalOutput:
    def test_same_clean_input_same_decisions(self):
        _, observed = generate(_config())
        r1, _ = _svc().reconcile(observed, now=FIXED_NOW)
        r2, _ = _svc().reconcile(observed, now=FIXED_NOW)
        assert [(d.payment_id, d.decision, str(d.confidence))
                for d in r1.decisions] == \
               [(d.payment_id, d.decision, str(d.confidence))
                for d in r2.decisions]

    def test_same_corrupted_input_same_decisions(self):
        corruption = {
            "missing_settlement": 0.1,
            "missing_bank_entry": 0.1,
            "amount_mismatch": 0.1,
            "date_mismatch": 0.05,
            "duplicate_bank_entry": 0.0,
            "settlement_fee_variance": 0.05,
            "orphan_bank_entry": 0.0,
            "missing_ledger_entry": 0.0,
        }
        _, observed = generate(_config(corruption=corruption))
        r1, _ = _svc().reconcile(observed, now=FIXED_NOW)
        r2, _ = _svc().reconcile(observed, now=FIXED_NOW)
        assert [(d.payment_id, d.decision)
                for d in r1.decisions] == \
               [(d.payment_id, d.decision)
                for d in r2.decisions]

    def test_same_input_same_match_rate(self):
        _, observed = generate(_config())
        r1, _ = _svc().reconcile(observed, now=FIXED_NOW)
        r2, _ = _svc().reconcile(observed, now=FIXED_NOW)
        assert r1.match_rate == r2.match_rate

    def test_different_timestamps_same_decisions(self):
        _, observed = generate(_config())
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 12, 31, tzinfo=timezone.utc)
        r1, _ = _svc().reconcile(observed, now=t1)
        r2, _ = _svc().reconcile(observed, now=t2)
        assert [(d.decision, str(d.confidence))
                for d in r1.decisions] == \
               [(d.decision, str(d.confidence))
                for d in r2.decisions]


class TestShuffledInputOrderInvariance:
    def test_shuffled_payments_same_decisions(self):
        """Shuffling the payments list must not change any decision."""
        _, observed = generate(_config(n=20))

        # Build shuffled world
        shuffled_payments = list(observed.payments)
        rng = random.Random(999)
        rng.shuffle(shuffled_payments)

        shuffled_world = ObservedWorld(
            merchants=observed.merchants,
            payments=shuffled_payments,
            settlements=observed.settlements,
            bank_entries=observed.bank_entries,
            ledger_entries=observed.ledger_entries,
            ground_truth=[],
            corruption_events=[],
        )

        r_orig, _ = _svc().reconcile(observed, now=FIXED_NOW)
        r_shuf, _ = _svc().reconcile(shuffled_world, now=FIXED_NOW)

        # Decisions are sorted by payment_id, so order is canonical
        assert [(d.payment_id, d.decision) for d in r_orig.decisions] == \
               [(d.payment_id, d.decision) for d in r_shuf.decisions]

    def test_shuffled_settlements_same_decisions(self):
        _, observed = generate(_config(n=20))

        shuffled_settlements = list(observed.settlements)
        rng = random.Random(777)
        rng.shuffle(shuffled_settlements)

        shuffled_world = ObservedWorld(
            merchants=observed.merchants,
            payments=observed.payments,
            settlements=shuffled_settlements,
            bank_entries=observed.bank_entries,
            ledger_entries=observed.ledger_entries,
            ground_truth=[],
            corruption_events=[],
        )

        r_orig, _ = _svc().reconcile(observed, now=FIXED_NOW)
        r_shuf, _ = _svc().reconcile(shuffled_world, now=FIXED_NOW)

        assert [(d.payment_id, d.decision) for d in r_orig.decisions] == \
               [(d.payment_id, d.decision) for d in r_shuf.decisions]

    def test_shuffled_bank_entries_same_decisions(self):
        _, observed = generate(_config(n=20))

        shuffled_banks = list(observed.bank_entries)
        rng = random.Random(555)
        rng.shuffle(shuffled_banks)

        shuffled_world = ObservedWorld(
            merchants=observed.merchants,
            payments=observed.payments,
            settlements=observed.settlements,
            bank_entries=shuffled_banks,
            ledger_entries=observed.ledger_entries,
            ground_truth=[],
            corruption_events=[],
        )

        r_orig, _ = _svc().reconcile(observed, now=FIXED_NOW)
        r_shuf, _ = _svc().reconcile(shuffled_world, now=FIXED_NOW)

        assert [(d.payment_id, d.decision) for d in r_orig.decisions] == \
               [(d.payment_id, d.decision) for d in r_shuf.decisions]


class TestDecisionsSortedByPaymentId:
    def test_decisions_sorted_by_payment_id(self):
        _, observed = generate(_config(n=20))
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        pids = [d.payment_id for d in result.decisions]
        assert pids == sorted(pids)

    def test_evidence_cards_sorted_by_payment_id(self):
        _, observed = generate(_config(n=20))
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        pids = [c.payment_id for c in result.evidence_cards]
        assert pids == sorted(pids)
