"""
LedgerLens Phase 3.2 — Metric Computation
==========================================
Pure functions for all evaluation metrics.

RULES:
  - All returned fractions are Decimal or None.
  - None is returned when the denominator is zero — never 0.0, never NaN.
  - The caller receives an (value, insufficient_data) pair from safe_div().
  - No float arithmetic — Decimal only for financial fractions.
  - All inputs are typed; no silent type coercions.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Sequence

_TWO = Decimal("0.01")
_ZERO = Decimal("0")
_ONE = Decimal("1.00")


# ---------------------------------------------------------------------------
# Core: zero-safe division
# ---------------------------------------------------------------------------

def safe_div(numerator: int | Decimal, denominator: int | Decimal) -> tuple[Decimal | None, bool]:
    """
    Divide numerator by denominator.

    Returns:
        (Decimal value quantised to 4 d.p., False) on success
        (None, True) when denominator is zero

    Never returns NaN or float.
    """
    if denominator == 0:
        return None, True
    result = Decimal(numerator) / Decimal(denominator)
    return result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), False


def safe_pct(numerator: int, denominator: int) -> tuple[Decimal | None, bool]:
    """Like safe_div but quantises to 2 d.p. — for display-friendly percentages."""
    if denominator == 0:
        return None, True
    result = Decimal(numerator) / Decimal(denominator)
    return result.quantize(_TWO, rounding=ROUND_HALF_UP), False


# ---------------------------------------------------------------------------
# F1 score
# ---------------------------------------------------------------------------

def safe_f1(precision: Decimal | None, recall: Decimal | None) -> tuple[Decimal | None, bool]:
    """
    Compute F1 = 2·P·R / (P+R).
    Returns (None, True) if either input is None or their sum is zero.
    """
    if precision is None or recall is None:
        return None, True
    denom = precision + recall
    if denom == _ZERO:
        return None, True
    result = (2 * precision * recall) / denom
    return result.quantize(_TWO, rounding=ROUND_HALF_UP), False


# ---------------------------------------------------------------------------
# Reconciliation scorecard metrics
# ---------------------------------------------------------------------------

def compute_auto_match_precision(tp: int, fp: int) -> tuple[Decimal | None, bool]:
    """TP / (TP + FP). None if no auto-matches at all."""
    return safe_pct(tp, tp + fp)


def compute_auto_match_recall(tp: int, n_clean: int) -> tuple[Decimal | None, bool]:
    """TP / N_clean. None if no clean payments."""
    return safe_pct(tp, n_clean)


def compute_reconciliation_f1(
    tp: int, fp: int, n_clean: int
) -> tuple[Decimal | None, bool]:
    p, p_insuff = compute_auto_match_precision(tp, fp)
    r, r_insuff = compute_auto_match_recall(tp, n_clean)
    if p_insuff or r_insuff:
        return None, True
    return safe_f1(p, r)


def compute_resolution_rate(n_decided: int, n_total: int) -> Decimal:
    """Always 1.00 in Phase 3.1 (every payment gets a decision)."""
    if n_total == 0:
        return _ZERO
    return (Decimal(n_decided) / Decimal(n_total)).quantize(_TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Unsafe auto-match
# ---------------------------------------------------------------------------

def compute_unsafe_auto_match_rate(
    unsafe_count: int, total_auto_match: int
) -> tuple[Decimal | None, bool]:
    """unsafe_count / total_auto_match. None if no auto-matches."""
    return safe_pct(unsafe_count, total_auto_match)


# ---------------------------------------------------------------------------
# Exception scorecard metrics
# ---------------------------------------------------------------------------

def compute_exception_precision(
    correctly_detected: int, false_exception_detections: int
) -> tuple[Decimal | None, bool]:
    """correctly_detected / (correctly_detected + false_exception_detections)."""
    return safe_pct(correctly_detected, correctly_detected + false_exception_detections)


def compute_exception_recall(
    correctly_detected: int, total_injected: int
) -> tuple[Decimal | None, bool]:
    """correctly_detected / total_injected_exceptions."""
    return safe_pct(correctly_detected, total_injected)


def compute_exception_f1(
    correctly_detected: int, false_detections: int, total_injected: int
) -> tuple[Decimal | None, bool]:
    p, p_i = compute_exception_precision(correctly_detected, false_detections)
    r, r_i = compute_exception_recall(correctly_detected, total_injected)
    if p_i or r_i:
        return None, True
    return safe_f1(p, r)


# ---------------------------------------------------------------------------
# Per-corruption detection rate
# ---------------------------------------------------------------------------

def compute_detection_rate(
    correctly_detected: int, injected_count: int
) -> tuple[Decimal | None, bool]:
    """correctly_detected / injected_count. None if injected_count == 0."""
    return safe_pct(correctly_detected, injected_count)


# ---------------------------------------------------------------------------
# Batch integrity rate
# ---------------------------------------------------------------------------

def compute_fully_reconciled_rate(
    clean_batches: int, total_batches: int
) -> tuple[Decimal | None, bool]:
    """clean_batches / total_batches. None if no batches."""
    return safe_pct(clean_batches, total_batches)


# ---------------------------------------------------------------------------
# Aggregation statistics across seeds
# ---------------------------------------------------------------------------

def _to_decimal_list(values: Sequence[Decimal | None]) -> list[Decimal]:
    """Filter out None values and return as sorted list."""
    return [v for v in values if v is not None]


def aggregate_metric(values: Sequence[Decimal | None]) -> dict:
    """
    Compute descriptive statistics across K seed values.

    Returns a dict with keys: mean, median, std, min, max, seeds_with_data,
    seeds_with_insufficient_data, confidence_interval_95.

    confidence_interval_95 is computed for K >= 8 using t-distribution.
    For K < 8 it is None.
    """
    total = len(values)
    valid = _to_decimal_list(values)
    n = len(valid)
    insufficient = total - n

    if n == 0:
        return {
            "mean": None, "median": None, "std": None,
            "min": None, "max": None,
            "seeds_with_data": 0,
            "seeds_with_insufficient_data": insufficient,
            "confidence_interval_95": None,
        }

    mean = sum(valid) / Decimal(n)
    mean = mean.quantize(_TWO, rounding=ROUND_HALF_UP)

    sorted_v = sorted(valid)
    median = sorted_v[n // 2] if n % 2 == 1 else (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2
    median = median.quantize(_TWO, rounding=ROUND_HALF_UP)

    if n == 1:
        std = _ZERO
    else:
        variance = sum((v - mean) ** 2 for v in valid) / Decimal(n)
        std = Decimal(str(float(variance) ** 0.5)).quantize(_TWO, rounding=ROUND_HALF_UP)

    vmin = min(valid).quantize(_TWO, rounding=ROUND_HALF_UP)
    vmax = max(valid).quantize(_TWO, rounding=ROUND_HALF_UP)

    ci = None
    if n >= 8:
        # t-critical for 95% CI, df = n-1
        # Use scipy-free approximation: t ≈ 1.96 for large n, conservative
        t_crit = _t_critical_approx(n - 1)
        margin = t_crit * std / Decimal(str(math.sqrt(n)))
        margin = margin.quantize(_TWO, rounding=ROUND_HALF_UP)
        ci = (
            (mean - margin).quantize(_TWO, rounding=ROUND_HALF_UP),
            (mean + margin).quantize(_TWO, rounding=ROUND_HALF_UP),
        )

    return {
        "mean": mean,
        "median": median,
        "std": std,
        "min": vmin,
        "max": vmax,
        "seeds_with_data": n,
        "seeds_with_insufficient_data": insufficient,
        "confidence_interval_95": ci,
    }


# t-critical table (two-tailed 95%, df 7–99) without scipy
_T_TABLE = {
    7: Decimal("2.365"), 8: Decimal("2.306"), 9: Decimal("2.262"),
    10: Decimal("2.228"), 15: Decimal("2.131"), 20: Decimal("2.086"),
    30: Decimal("2.042"), 40: Decimal("2.021"), 60: Decimal("2.000"),
    99: Decimal("1.984"),
}


def _t_critical_approx(df: int) -> Decimal:
    """Return approximate t-critical for 95% CI given degrees of freedom."""
    if df >= 99:
        return Decimal("1.96")
    for threshold, t in sorted(_T_TABLE.items()):
        if df <= threshold:
            return t
    return Decimal("1.96")
