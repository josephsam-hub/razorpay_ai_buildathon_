"""
Tests — Evaluator: end-to-end evaluation using generate() + reconcile() + evaluate().

Covers:
  - zero-corruption dataset: all TP_MATCH, zero unsafe auto-match
  - full corruption profile: per-type metrics populated
  - E008 two-level evaluation: payment AUTO_MATCH + orphan entity detected
  - E007 unsafe auto-match measured (expected: nonzero)
  - ground truth never in BatchReconciliationResult
  - no GroundTruth import in reconciliation modules
  - deterministic evaluation (same inputs → same result)
  - entity findings entity_type and payment_id
  - ABSTAIN on corrupt = conservative TN
"""

from __future__ import annotations

import importlib
import sys
from decimal import Decimal

import pytest

from app.core.evaluation.evaluator import Evaluator
from app.data.generator.config import DatasetConfig
from app.data.generator.world import generate
from app.models.decisions import BatchReconciliationResult
from app.services.reconciliation import ReconciliationService
from app.services.evaluation import EvaluationService

from tests.evaluation.conftest import (
    FIXED_NOW,
    _full_corruption_config,
    _zero_corruption_config,
)


def _run(cfg: DatasetConfig):
    _clean, observed = generate(cfg)
    svc = ReconciliationService()
    result, _ = svc.reconcile(observed, now=FIXED_NOW)
    evaluator = Evaluator()
    per_seed = evaluator.evaluate(
        result=result,
        observed=observed,
        seed=cfg.seed,
        dataset_version=cfg.version,
    )
    return per_seed, result, observed


class TestZeroCorruption:
    def test_all_tp_match(self):
        psr, _, _ = _run(_zero_corruption_config())
        sc = psr.reconciliation_scorecard
        assert sc.incorrect_match_count == 0
        assert sc.missed_match_count == 0
        assert sc.correct_match_count == sc.auto_matched_count

    def test_precision_is_one(self):
        psr, _, _ = _run(_zero_corruption_config())
        p = psr.reconciliation_scorecard.auto_match_precision
        assert p is not None
        assert p == Decimal("1.00")

    def test_unsafe_auto_match_is_zero(self):
        psr, _, _ = _run(_zero_corruption_config())
        assert psr.unsafe_auto_match_metrics.unsafe_auto_match_count == 0
        rate = psr.unsafe_auto_match_metrics.unsafe_auto_match_rate
        assert rate == Decimal("0.00")

    def test_no_exception_records(self):
        psr, _, _ = _run(_zero_corruption_config())
        assert psr.exception_scorecard.missed_exceptions == 0

    def test_entity_findings_all_tp(self):
        psr, _, _ = _run(_zero_corruption_config())
        payment_findings = [f for f in psr.entity_findings if f.entity_type == "payment"]
        for f in payment_findings:
            assert f.payment_outcome == "TP_MATCH"

    def test_no_unsafe_by_corruption(self):
        psr, _, _ = _run(_zero_corruption_config())
        for count in psr.unsafe_auto_match_metrics.unsafe_auto_match_by_corruption.values():
            assert count == 0


class TestFullCorruptionProfile:
    def test_per_corruption_metrics_populated(self):
        psr, _, _ = _run(_full_corruption_config(seed=42, n=50))
        assert len(psr.per_corruption_metrics) == 8
        types = {m.corruption_type for m in psr.per_corruption_metrics}
        expected = {
            "missing_settlement", "missing_bank_entry", "missing_ledger_entry",
            "amount_mismatch", "date_mismatch", "duplicate_bank_entry",
            "settlement_fee_variance", "orphan_bank_entry",
        }
        assert types == expected

    def test_e007_likely_false_positive(self):
        """E007 (fee_variance) known gap — evaluator measures unsafe auto-match."""
        psr, _, _ = _run(_full_corruption_config(seed=42, n=100))
        e007 = next(
            m for m in psr.per_corruption_metrics
            if m.corruption_type == "settlement_fee_variance"
        )
        # Detection rate may be 0.0 — E007 is a known gap in Phase 3.1
        # We only assert it was measured (not None if any were injected)
        if e007.injected_count > 0:
            # Either detected or missed — both are valid measurement outcomes
            total = e007.correctly_detected_count + e007.auto_matched_incorrectly_count
            assert total == e007.injected_count

    def test_unsafe_metrics_decimal(self):
        psr, _, _ = _run(_full_corruption_config())
        rate = psr.unsafe_auto_match_metrics.unsafe_auto_match_rate
        if rate is not None:
            assert isinstance(rate, Decimal)
            assert not isinstance(rate, float)

    def test_reconciliation_scorecard_counts_sum(self):
        psr, _, _ = _run(_full_corruption_config())
        sc = psr.reconciliation_scorecard
        total_classified = (
            sc.correct_match_count
            + sc.incorrect_match_count
            + sc.correct_exception_count
            + sc.abstained_corrupt_count
            + sc.missed_match_count
            + sc.abstained_clean_count
        )
        assert total_classified == sc.total_payments

    def test_decision_distribution_sums(self):
        psr, result, _ = _run(_full_corruption_config())
        dist = psr.decision_distribution
        assert (dist["auto_matched"] + dist["human_review"] + dist["abstained"]
                == psr.reconciliation_scorecard.total_payments)


class TestE008OrphanTwoLevel:
    def test_payment_may_auto_match_while_orphan_detected(self):
        """
        E008: the affected payment's own bank entry is unchanged.
        The payment may AUTO_MATCH correctly while the orphan bank entry
        is surfaced separately. Both are evaluated independently.
        """
        cfg = DatasetConfig.model_validate({
            "version": "test", "n_payments": 30, "n_merchants": 3,
            "seed": 77, "currency": "INR",
            "start_date": "2026-08-01", "end_date": "2026-08-31",
            "corruption": {k: 0.0 for k in [
                "missing_settlement", "missing_bank_entry", "missing_ledger_entry",
                "amount_mismatch", "date_mismatch", "duplicate_bank_entry",
                "settlement_fee_variance",
            ]} | {"orphan_bank_entry": 0.10},
        })
        psr, result, observed = _run(cfg)

        n_orphan_injected = sum(
            1 for ce in observed.corruption_events
            if ce.corruption_type == "orphan_bank_entry"
        )
        if n_orphan_injected == 0:
            pytest.skip("No orphan injected for this seed — adjust n or seed")

        # Orphan entities must appear in entity_findings with entity_type=bank_entry
        orphan_findings = [
            f for f in psr.entity_findings
            if f.entity_type == "bank_entry"
        ]
        assert len(orphan_findings) >= n_orphan_injected

        # Orphan findings must have payment_id = None
        for f in orphan_findings:
            assert f.payment_id is None, "Orphan bank entry must have null payment_id"

    def test_orphan_detected_in_exception_scorecard(self):
        cfg = DatasetConfig.model_validate({
            "version": "test", "n_payments": 30, "n_merchants": 3,
            "seed": 77, "currency": "INR",
            "start_date": "2026-08-01", "end_date": "2026-08-31",
            "corruption": {k: 0.0 for k in [
                "missing_settlement", "missing_bank_entry", "missing_ledger_entry",
                "amount_mismatch", "date_mismatch", "duplicate_bank_entry",
                "settlement_fee_variance",
            ]} | {"orphan_bank_entry": 0.10},
        })
        psr, _, observed = _run(cfg)
        n_injected = sum(
            1 for ce in observed.corruption_events
            if ce.corruption_type == "orphan_bank_entry"
        )
        if n_injected == 0:
            pytest.skip("No orphan injected")
        # Total injected exceptions includes orphan entities
        assert psr.exception_scorecard.total_injected_exceptions >= n_injected


class TestGroundTruthIsolation:
    def test_batch_result_has_no_ground_truth_fields(self):
        """BatchReconciliationResult must not expose GroundTruth data."""
        _clean, observed = generate(_zero_corruption_config())
        svc = ReconciliationService()
        result, _ = svc.reconcile(observed)
        # result must not have ground_truth or corruption_events attributes
        assert not hasattr(result, "ground_truth")
        assert not hasattr(result, "corruption_events")

    def test_reconciliation_modules_do_not_import_groundtruth(self):
        """
        The reconciliation engine modules must not import GroundTruth.
        This verifies the hard architectural boundary.
        """
        recon_modules = [
            "app.core.reconciliation.exact",
            "app.core.reconciliation.composite",
            "app.core.reconciliation.engine",
            "app.core.reconciliation.normaliser",
            "app.core.reconciliation.validation",
        ]
        for mod_name in recon_modules:
            mod = importlib.import_module(mod_name)
            src = getattr(mod, "__file__", "") or ""
            # Read the source to check for GroundTruth import
            import pathlib
            if src:
                content = pathlib.Path(src).read_text(encoding="utf-8")
                assert "GroundTruth" not in content, \
                    f"{mod_name} must not import GroundTruth"


class TestDeterminism:
    def test_same_seed_same_result(self):
        cfg = _full_corruption_config(seed=42, n=30)
        psr1, _, _ = _run(cfg)
        psr2, _, _ = _run(cfg)
        assert (psr1.reconciliation_scorecard.correct_match_count
                == psr2.reconciliation_scorecard.correct_match_count)
        assert (psr1.unsafe_auto_match_metrics.unsafe_auto_match_count
                == psr2.unsafe_auto_match_metrics.unsafe_auto_match_count)

    def test_different_seeds_different_profiles(self):
        psr1, _, _ = _run(_full_corruption_config(seed=42, n=50))
        psr2, _, _ = _run(_full_corruption_config(seed=43, n=50))
        # At least one corruption count should differ
        assert psr1.corruption_profile != psr2.corruption_profile


class TestEvaluationServiceHoldoutGuard:
    def test_holdout_seed_raises(self):
        svc = EvaluationService()
        cfg = _zero_corruption_config(seed=999)
        with pytest.raises(ValueError, match="holdout"):
            svc.evaluate_seed(cfg, seed=999, allow_holdout=False)

    def test_non_holdout_seed_ok(self):
        svc = EvaluationService()
        cfg = _zero_corruption_config(seed=100)
        psr = svc.evaluate_seed(cfg, seed=100)
        assert psr.seed == 100
