"""
Tests — metrics.py: pure Decimal-safe metric functions.

Covers every formula, every zero-denominator case, and type safety.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.evaluation.metrics import (
    aggregate_metric,
    compute_auto_match_precision,
    compute_auto_match_recall,
    compute_detection_rate,
    compute_exception_f1,
    compute_exception_precision,
    compute_exception_recall,
    compute_fully_reconciled_rate,
    compute_reconciliation_f1,
    compute_resolution_rate,
    compute_unsafe_auto_match_rate,
    safe_div,
    safe_f1,
    safe_pct,
)


class TestSafeDiv:
    def test_normal_division(self):
        v, i = safe_div(3, 4)
        assert isinstance(v, Decimal)
        assert not isinstance(v, float)
        assert i is False

    def test_zero_denominator_returns_none(self):
        v, i = safe_div(5, 0)
        assert v is None
        assert i is True

    def test_zero_numerator(self):
        v, i = safe_div(0, 10)
        assert v == Decimal("0")
        assert i is False

    def test_decimal_inputs(self):
        v, i = safe_div(Decimal("3"), Decimal("4"))
        assert isinstance(v, Decimal)
        assert i is False


class TestSafePct:
    def test_precision_two_dp(self):
        v, i = safe_pct(1, 3)
        assert v is not None
        assert str(v).count(".") == 1
        # 1/3 = 0.3333... → rounds to 0.33
        assert v == Decimal("0.33")

    def test_zero_denominator(self):
        v, i = safe_pct(1, 0)
        assert v is None
        assert i is True


class TestSafeF1:
    def test_both_none(self):
        v, i = safe_f1(None, None)
        assert v is None
        assert i is True

    def test_one_none(self):
        v, i = safe_f1(Decimal("0.8"), None)
        assert v is None

    def test_both_zero(self):
        v, i = safe_f1(Decimal("0"), Decimal("0"))
        assert v is None

    def test_normal(self):
        v, i = safe_f1(Decimal("0.80"), Decimal("0.80"))
        assert v == Decimal("0.80")
        assert i is False

    def test_asymmetric(self):
        # P=1.0, R=0.5 → F1 = 2*1*0.5/(1+0.5) = 0.67
        v, i = safe_f1(Decimal("1.00"), Decimal("0.50"))
        assert v is not None
        assert v == Decimal("0.67")


class TestAutoMatchPrecision:
    def test_perfect(self):
        v, i = compute_auto_match_precision(10, 0)
        assert v == Decimal("1.00")
        assert i is False

    def test_with_fp(self):
        # 8 TP, 2 FP → 8/10 = 0.80
        v, i = compute_auto_match_precision(8, 2)
        assert v == Decimal("0.80")

    def test_zero_denominator(self):
        v, i = compute_auto_match_precision(0, 0)
        assert v is None
        assert i is True

    def test_returns_decimal_not_float(self):
        v, _ = compute_auto_match_precision(5, 5)
        assert isinstance(v, Decimal)
        assert not isinstance(v, float)


class TestAutoMatchRecall:
    def test_perfect(self):
        v, i = compute_auto_match_recall(10, 10)
        assert v == Decimal("1.00")

    def test_partial(self):
        # 7 TP of 10 clean → 0.70
        v, i = compute_auto_match_recall(7, 10)
        assert v == Decimal("0.70")

    def test_zero_clean(self):
        v, i = compute_auto_match_recall(0, 0)
        assert v is None
        assert i is True


class TestReconciliationF1:
    def test_perfect(self):
        v, i = compute_reconciliation_f1(10, 0, 10)
        assert v == Decimal("1.00")

    def test_none_on_zero_precision_denominator(self):
        # TP=0, FP=0 → precision=None → F1=None
        v, i = compute_reconciliation_f1(0, 0, 10)
        assert v is None
        assert i is True

    def test_none_on_zero_clean(self):
        v, i = compute_reconciliation_f1(0, 5, 0)
        assert v is None


class TestResolutionRate:
    def test_always_one_when_all_decided(self):
        v = compute_resolution_rate(20, 20)
        assert v == Decimal("1.00")

    def test_zero_total(self):
        v = compute_resolution_rate(0, 0)
        assert v == Decimal("0")


class TestUnsafeAutoMatchRate:
    def test_zero_unsafe(self):
        v, i = compute_unsafe_auto_match_rate(0, 10)
        assert v == Decimal("0.00")
        assert i is False

    def test_some_unsafe(self):
        # 3 unsafe of 10 → 0.30
        v, i = compute_unsafe_auto_match_rate(3, 10)
        assert v == Decimal("0.30")

    def test_no_auto_matches(self):
        v, i = compute_unsafe_auto_match_rate(0, 0)
        assert v is None
        assert i is True

    def test_returns_decimal(self):
        v, _ = compute_unsafe_auto_match_rate(1, 5)
        assert isinstance(v, Decimal)


class TestExceptionMetrics:
    def test_perfect_precision_recall(self):
        ep, ei = compute_exception_precision(10, 0)
        er, eri = compute_exception_recall(10, 10)
        ef, efi = compute_exception_f1(10, 0, 10)
        assert ep == Decimal("1.00")
        assert er == Decimal("1.00")
        assert ef == Decimal("1.00")

    def test_zero_injected_recall_null(self):
        v, i = compute_exception_recall(0, 0)
        assert v is None
        assert i is True

    def test_zero_detected_precision_null(self):
        v, i = compute_exception_precision(0, 0)
        assert v is None
        assert i is True

    def test_f1_null_when_inputs_null(self):
        v, i = compute_exception_f1(0, 0, 0)
        assert v is None


class TestDetectionRate:
    def test_full_detection(self):
        v, i = compute_detection_rate(5, 5)
        assert v == Decimal("1.00")

    def test_partial_detection(self):
        v, i = compute_detection_rate(3, 5)
        assert v == Decimal("0.60")

    def test_zero_injected(self):
        v, i = compute_detection_rate(0, 0)
        assert v is None
        assert i is True


class TestFullyReconciledRate:
    def test_all_clean(self):
        v, i = compute_fully_reconciled_rate(10, 10)
        assert v == Decimal("1.00")

    def test_zero_batches(self):
        v, i = compute_fully_reconciled_rate(0, 0)
        assert v is None
        assert i is True

    def test_partial(self):
        v, i = compute_fully_reconciled_rate(7, 10)
        assert v == Decimal("0.70")


class TestAggregateMetric:
    def test_all_none(self):
        result = aggregate_metric([None, None, None])
        assert result["mean"] is None
        assert result["seeds_with_data"] == 0
        assert result["seeds_with_insufficient_data"] == 3

    def test_single_value(self):
        result = aggregate_metric([Decimal("0.80")])
        assert result["mean"] == Decimal("0.80")
        assert result["std"] == Decimal("0.00")
        assert result["confidence_interval_95"] is None  # K < 8

    def test_mixed_none_and_values(self):
        result = aggregate_metric([Decimal("0.80"), None, Decimal("0.60")])
        # mean of 0.80 and 0.60 = 0.70
        assert result["mean"] == Decimal("0.70")
        assert result["seeds_with_data"] == 2
        assert result["seeds_with_insufficient_data"] == 1

    def test_all_decimal_output(self):
        result = aggregate_metric([Decimal("0.9"), Decimal("0.8"), Decimal("0.7")])
        for key in ("mean", "median", "std", "min", "max"):
            if result[key] is not None:
                assert isinstance(result[key], Decimal), f"{key} should be Decimal"

    def test_no_float_in_output(self):
        result = aggregate_metric([Decimal("1.0"), Decimal("0.5")])
        for key in ("mean", "median", "std", "min", "max"):
            assert not isinstance(result[key], float), f"{key} must not be float"
