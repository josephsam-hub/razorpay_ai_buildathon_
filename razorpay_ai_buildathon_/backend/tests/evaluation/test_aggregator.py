"""
Tests — MultiSeedAggregator.

Covers multi-seed aggregation, duplicate seed guard, partition validation,
holdout guard, None metric handling, and statistical correctness.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.evaluation.aggregator import MultiSeedAggregator
from app.services.evaluation import EvaluationService

from tests.evaluation.conftest import _zero_corruption_config


def _eval_seeds(seeds: list[int], n: int = 20):
    svc = EvaluationService()
    cfg_base = _zero_corruption_config(n=n)
    results = []
    for s in seeds:
        results.append(svc.evaluate_seed(cfg_base, seed=s))
    return results


class TestAggregatorBasic:
    def test_single_seed(self):
        agg = MultiSeedAggregator()
        results = _eval_seeds([100])
        report = agg.aggregate(results, run_id="TEST_001", partition="evaluation")
        assert report.seed_count == 1
        assert report.seed_list == [100]

    def test_multi_seed_mean_computed(self):
        agg = MultiSeedAggregator()
        results = _eval_seeds([100, 101, 102])
        report = agg.aggregate(results, run_id="TEST_002", partition="evaluation")
        assert report.auto_match_precision is not None
        assert report.auto_match_precision.mean is not None
        assert isinstance(report.auto_match_precision.mean, Decimal)

    def test_per_seed_results_preserved(self):
        agg = MultiSeedAggregator()
        results = _eval_seeds([100, 101])
        report = agg.aggregate(results, run_id="TEST_003")
        assert len(report.per_seed_results) == 2
        assert {r.seed for r in report.per_seed_results} == {100, 101}


class TestDuplicateSeedGuard:
    def test_duplicate_seed_raises(self):
        agg = MultiSeedAggregator()
        results = _eval_seeds([100, 100])  # duplicate
        with pytest.raises(ValueError, match="Duplicate"):
            agg.aggregate(results, run_id="TEST_DUP")


class TestHoldoutGuard:
    def test_holdout_seed_blocked_in_evaluation_partition(self):
        agg = MultiSeedAggregator()
        results = _eval_seeds([100])
        # Manually patch seed to 999 to simulate accident
        from app.models.evaluation import PerSeedResult
        patched = []
        for r in results:
            # Build a copy with seed=999 (frozen model — use model_copy)
            patched.append(r.model_copy(update={"seed": 999}))
        with pytest.raises(ValueError, match="holdout"):
            agg.aggregate(patched, run_id="TEST_HOLD", partition="evaluation")


class TestPartitionInference:
    def test_calibration_seeds_inferred(self):
        agg = MultiSeedAggregator()
        results = _eval_seeds([42, 43])
        report = agg.aggregate(results, run_id="CAL")
        assert report.partition == "calibration"

    def test_evaluation_seeds_inferred(self):
        agg = MultiSeedAggregator()
        results = _eval_seeds([100, 101])
        report = agg.aggregate(results, run_id="EVAL")
        assert report.partition == "evaluation"


class TestAggregateMetricStats:
    def test_zero_corruption_all_precision_one(self):
        """All seeds with 0 corruption → precision = 1.00 across all seeds."""
        agg = MultiSeedAggregator()
        results = _eval_seeds([100, 101, 102])
        report = agg.aggregate(results, run_id="TEST_PREC")
        p = report.auto_match_precision
        assert p is not None
        assert p.mean == Decimal("1.00")
        assert p.std == Decimal("0.00")

    def test_empty_results_raises(self):
        agg = MultiSeedAggregator()
        with pytest.raises(ValueError):
            agg.aggregate([], run_id="EMPTY")

    def test_metrics_are_decimal_not_float(self):
        agg = MultiSeedAggregator()
        results = _eval_seeds([100])
        report = agg.aggregate(results, run_id="TYPE_CHECK")
        for attr in (
            "auto_match_precision", "auto_match_recall", "reconciliation_f1",
            "unsafe_auto_match_rate",
        ):
            summary = getattr(report, attr)
            if summary and summary.mean is not None:
                assert isinstance(summary.mean, Decimal), f"{attr}.mean must be Decimal"
                assert not isinstance(summary.mean, float)
