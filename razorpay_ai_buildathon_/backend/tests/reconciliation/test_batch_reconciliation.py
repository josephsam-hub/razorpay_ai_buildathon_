"""
Tests — Batch reconciliation (ReconciliationService + BatchReconciliationResult).

Covers:
  - one decision per payment
  - empty batch
  - match_rate and exception_rate calculation
  - zero-corruption dataset → all AUTO_MATCH
  - batch with all 8 corruption types handled without crash
  - decisions list sorted by payment_id
  - aggregate counts consistent with decisions list
  - Decimal rates
  - batch_id generated deterministically
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.data.generator.config import DatasetConfig
from app.data.generator.world import generate, ObservedWorld
from app.services.reconciliation import ReconciliationService

from tests.reconciliation.conftest import (
    FIXED_NOW,
    make_bank_entry,
    make_clean_world,
    make_ledger_entry,
    make_merchant,
    make_payment,
    make_settlement,
)


def _svc():
    return ReconciliationService()


def _config(**overrides) -> DatasetConfig:
    base = {
        "version": "test",
        "n_payments": 20,
        "n_merchants": 3,
        "seed": 42,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
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
    }
    base.update(overrides)
    return DatasetConfig.model_validate(base)


class TestBatchOneDecisionPerPayment:
    def test_exactly_one_decision_per_payment(self):
        _, observed = generate(_config())
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        assert result.total_records == len(observed.payments)
        assert len(result.decisions) == len(observed.payments)

    def test_exactly_one_evidence_card_per_payment(self):
        _, observed = generate(_config())
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        assert len(result.evidence_cards) == len(observed.payments)

    def test_decision_payment_ids_match_observed_payments(self):
        _, observed = generate(_config())
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        observed_pids = sorted(p.payment_id for p in observed.payments)
        decision_pids = [d.payment_id for d in result.decisions]
        assert decision_pids == observed_pids


class TestEmptyBatch:
    def test_empty_world_total_records_zero(self):
        world = ObservedWorld(
            merchants=[], payments=[], settlements=[],
            bank_entries=[], ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        result, exceptions = _svc().reconcile(world, now=FIXED_NOW)
        assert result.total_records == 0
        assert result.auto_matched == 0
        assert result.human_review == 0
        assert result.abstained == 0
        assert result.decisions == []
        assert exceptions == []

    def test_empty_world_match_rate_is_zero(self):
        world = ObservedWorld(
            merchants=[], payments=[], settlements=[],
            bank_entries=[], ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        result, _ = _svc().reconcile(world, now=FIXED_NOW)
        assert result.match_rate == Decimal("0")

    def test_empty_world_batch_id_is_empty(self):
        world = ObservedWorld(
            merchants=[], payments=[], settlements=[],
            bank_entries=[], ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        result, _ = _svc().reconcile(world, now=FIXED_NOW)
        assert result.batch_id == "BATCH_EMPTY"


class TestZeroCorruptionAllAutoMatch:
    def test_clean_dataset_all_auto_match(self):
        _, observed = generate(_config())
        result, exceptions = _svc().reconcile(observed, now=FIXED_NOW)
        assert result.auto_matched == result.total_records
        assert result.human_review == 0
        assert result.abstained == 0
        assert result.match_rate == Decimal("1.00")
        assert exceptions == []

    def test_clean_all_confidence_one(self):
        _, observed = generate(_config())
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        for d in result.decisions:
            assert d.confidence == Decimal("1.00")


class TestMetricsAccuracy:
    def test_match_rate_is_decimal(self):
        _, observed = generate(_config())
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        assert isinstance(result.match_rate, Decimal)
        assert not isinstance(result.match_rate, float)

    def test_exception_rate_is_decimal(self):
        _, observed = generate(_config())
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        assert isinstance(result.exception_rate, Decimal)

    def test_match_rate_plus_exception_rate_equals_one(self):
        _, observed = generate(_config())
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        # Rates are rounded independently so the sum may differ by 0.01
        total = result.match_rate + result.exception_rate
        assert abs(total - Decimal("1.00")) <= Decimal("0.01")

    def test_counts_sum_to_total(self):
        _, observed = generate(_config())
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        assert result.auto_matched + result.human_review + result.abstained == result.total_records

    def test_exception_records_count_matches_non_auto(self):
        """ExceptionRecord count must equal human_review + abstained."""
        cfg = {
            "version": "test",
            "n_payments": 20,
            "n_merchants": 3,
            "seed": 42,
            "currency": "INR",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "corruption": {
                "missing_settlement": 0.15,
                "missing_bank_entry": 0.10,
                "missing_ledger_entry": 0.0,
                "amount_mismatch": 0.10,
                "date_mismatch": 0.0,
                "duplicate_bank_entry": 0.0,
                "settlement_fee_variance": 0.0,
                "orphan_bank_entry": 0.0,
            },
        }
        _, observed = generate(DatasetConfig.model_validate(cfg))
        result, exceptions = _svc().reconcile(observed, now=FIXED_NOW)
        expected_exc = result.human_review + result.abstained
        assert len(exceptions) == expected_exc


class TestAllCorruptionTypesHandled:
    def test_all_corruption_types_no_crash(self):
        """Engine must handle all 8 corruption types without exception."""
        cfg = {
            "version": "test",
            "n_payments": 50,
            "n_merchants": 5,
            "seed": 77,
            "currency": "INR",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "corruption": {
                "missing_settlement": 0.05,
                "missing_bank_entry": 0.05,
                "missing_ledger_entry": 0.05,
                "amount_mismatch": 0.05,
                "date_mismatch": 0.05,
                "duplicate_bank_entry": 0.05,
                "settlement_fee_variance": 0.05,
                "orphan_bank_entry": 0.05,
            },
        }
        _, observed = generate(DatasetConfig.model_validate(cfg))
        # Should not raise
        result, exceptions = _svc().reconcile(observed, now=FIXED_NOW)
        assert result.total_records == len(observed.payments)
        assert result.auto_matched + result.human_review + result.abstained == result.total_records

    def test_no_agent_review_in_any_decision(self):
        cfg = {
            "version": "test",
            "n_payments": 50,
            "n_merchants": 5,
            "seed": 77,
            "currency": "INR",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "corruption": {
                "missing_settlement": 0.05,
                "missing_bank_entry": 0.05,
                "missing_ledger_entry": 0.05,
                "amount_mismatch": 0.05,
                "date_mismatch": 0.05,
                "duplicate_bank_entry": 0.05,
                "settlement_fee_variance": 0.05,
                "orphan_bank_entry": 0.05,
            },
        }
        _, observed = generate(DatasetConfig.model_validate(cfg))
        result, _ = _svc().reconcile(observed, now=FIXED_NOW)
        for d in result.decisions:
            assert d.decision != "AGENT_REVIEW"
