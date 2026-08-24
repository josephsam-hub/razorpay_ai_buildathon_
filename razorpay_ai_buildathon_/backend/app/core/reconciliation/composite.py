"""
LedgerLens Phase 3 — Composite Matching
=========================================
Stage 2 of the reconciliation cascade.

Composite matching scores a CanonicalTransaction against a set of candidate
records using multi-signal evidence. It is only reached when exact matching
fails to produce AUTO_MATCH.

IMPORTANT — NO INVENTED THRESHOLDS:
  The repository specification does NOT define numeric confidence thresholds
  for converting a composite score into AUTO_MATCH. This stage therefore:
    - Computes and exposes a deterministic composite score.
    - Produces per-signal MatchEvidence.
    - Does NOT emit AUTO_MATCH — that decision is reserved for exact matches
      only (confidence = 1.00) per the Phase 3.1 specification.
    - Returns a CompositeMatchResult that the engine uses to decide between
      HUMAN_REVIEW and ABSTAIN based on documented deterministic rules
      (see engine.py).

  TBD — REQUIRES SPECIFICATION: numeric thresholds for AUTO_MATCH via
  composite score, field weights, amount tolerance, date tolerance.

COMPOSITE SIGNALS (source: Documentation-21-08-26.md §8.2 Stage B):
  CS001  merchant_id agreement
  CS002  currency agreement
  CS003  amount proximity  (payment_amount vs settlement_net_amount)
  CS004  date window       (payment_date vs settlement_date, considering tier cycle)
  CS005  settlement_ref presence (structural link exists even if amounts differ)

DETERMINISM:
  - Signals evaluated in fixed declared order.
  - Decimal arithmetic throughout.
  - Candidate list sorted by settlement_id before scoring (stable key).
  - Ties on composite score broken by settlement_id lexicographic order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.models.canonical import CanonicalTransaction
from app.models.decisions import MatchEvidence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ZERO = Decimal("0")
_ONE = Decimal("1.00")
_TWO_PLACES = Decimal("0.01")

# Maximum date distance (in days) that still counts as within the settlement
# window for CS004. The domain supports 1-3 day settlement cycles (T1/T2/T3).
# With an additional tolerance buffer for date-mismatch corruptions (up to 5
# days shift per Phase 2 spec), a window of 0-8 days is plausible.
# TBD — REQUIRES SPECIFICATION: exact tolerance.
# Phase 3.1 uses the maximum clean settlement cycle (3 days) + max date
# mismatch shift (5 days) = 8 days as the outer bound for a "within window"
# check, scoring 1.0 at 0 days and 0.0 beyond 8 days.
_MAX_DATE_DISTANCE_DAYS = 8


# ---------------------------------------------------------------------------
# CompositeScore — per-signal breakdown
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CompositeScore:
    """
    Detailed composite scoring result for one CanonicalTransaction.

    score: Decimal in [0.00, 1.00] — unweighted mean of signal scores.
           TBD: weighted when specification provides weights.
    signals: list of MatchEvidence for every signal evaluated.
    has_any_signal: True if at least one signal matched positively.
    """

    score: Decimal
    signals: list[MatchEvidence]
    has_any_signal: bool


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def score_composite(ct: CanonicalTransaction) -> CompositeScore:
    """
    Score the composite signals for one CanonicalTransaction.

    Called by the engine when exact matching did not produce AUTO_MATCH.
    The transaction must have a settlement (is_no_candidate cases are
    handled upstream and never reach composite scoring).

    Returns a CompositeScore with all signal evidence.
    Never mutates the input.
    """
    signals: list[MatchEvidence] = []

    # Evaluate each signal and accumulate
    signals.append(_score_cs001_merchant(ct))
    signals.append(_score_cs002_currency(ct))
    signals.append(_score_cs003_amount(ct))
    signals.append(_score_cs004_date_window(ct))
    signals.append(_score_cs005_ref_presence(ct))

    # Unweighted mean (TBD: apply weights once specification provides them)
    # All signals are always evaluated so divisor is always len(signals).
    total = sum(s.score_contribution for s in signals)
    score = (total / Decimal(len(signals))).quantize(_TWO_PLACES)

    has_any = any(s.matched for s in signals)

    return CompositeScore(score=score, signals=signals, has_any_signal=has_any)


# ---------------------------------------------------------------------------
# Individual signal scorers
# ---------------------------------------------------------------------------

def _score_cs001_merchant(ct: CanonicalTransaction) -> MatchEvidence:
    """CS001: merchant_id must agree across payment and settlement layers."""
    matched = (
        ct.settlement_merchant_id is not None
        and ct.settlement_merchant_id == ct.merchant_id
    )
    return MatchEvidence(
        rule_id="CS001",
        rule_description="merchant_id agreement across payment and settlement",
        matched=matched,
        field_name="merchant_id",
        expected_value=ct.merchant_id,
        observed_value=ct.settlement_merchant_id,
        score_contribution=_ONE if matched else _ZERO,
    )


def _score_cs002_currency(ct: CanonicalTransaction) -> MatchEvidence:
    """
    CS002: currency agreement.

    NOTE: BankEntry and Settlement do not carry a currency field in the
    Phase 2 domain models. Only Payment carries currency explicitly.
    We check that the payment currency is 'INR' (the only supported currency
    per DatasetConfig). This is a presence/sanity check, not a cross-field
    comparison.
    TBD — REQUIRES SPECIFICATION if currency is added to Settlement/BankEntry.
    """
    matched = ct.currency == "INR"
    return MatchEvidence(
        rule_id="CS002",
        rule_description="currency is INR (only supported currency in Phase 3.1)",
        matched=matched,
        field_name="currency",
        expected_value="INR",
        observed_value=ct.currency,
        score_contribution=_ONE if matched else _ZERO,
    )


def _score_cs003_amount(ct: CanonicalTransaction) -> MatchEvidence:
    """
    CS003: amount proximity — payment_amount vs settlement_net_amount.

    For single-payment settlements: payment_amount ≈ settlement_net_amount
    (net = gross - fee, so net < payment_amount).
    For multi-payment settlements: net is shared across payments.

    Score:
      1.00 if bank_credit_amount == settlement_net_amount (exact bank match)
      0.50 if settlement_net_amount is present but bank is absent
      0.00 if settlement_net_amount is None

    Rationale: the most reliable financial check at composite stage is
    whether the bank credit equals the settlement net. If the bank is
    missing, partial credit is given for the settlement record alone.

    TBD — REQUIRES SPECIFICATION: tolerance bands for near-match scoring.
    """
    if ct.settlement_net_amount is None:
        return MatchEvidence(
            rule_id="CS003",
            rule_description="amount proximity: settlement_net_amount present",
            matched=False,
            field_name="bank_credit_amount",
            expected_value=str(ct.payment_amount),
            observed_value=None,
            score_contribution=_ZERO,
        )

    if ct.bank_credit_amount is not None:
        exact = ct.bank_credit_amount == ct.settlement_net_amount
        score = _ONE if exact else _ZERO
        return MatchEvidence(
            rule_id="CS003",
            rule_description="bank_credit_amount == settlement_net_amount",
            matched=exact,
            field_name="bank_credit_amount",
            expected_value=str(ct.settlement_net_amount),
            observed_value=str(ct.bank_credit_amount),
            score_contribution=score,
        )

    # Bank absent — partial credit for settlement presence
    partial = Decimal("0.50")
    return MatchEvidence(
        rule_id="CS003",
        rule_description="settlement_net_amount present (bank absent — partial credit)",
        matched=True,
        field_name="settlement_net_amount",
        expected_value=str(ct.payment_amount),
        observed_value=str(ct.settlement_net_amount),
        score_contribution=partial,
    )


def _score_cs004_date_window(ct: CanonicalTransaction) -> MatchEvidence:
    """
    CS004: date window check — settlement_date within expected range of payment_date.

    Score linearly from 1.0 (distance=0) to 0.0 (distance=_MAX_DATE_DISTANCE_DAYS).
    Beyond _MAX_DATE_DISTANCE_DAYS: score = 0.0.

    Linear formula: score = max(0, 1 - distance / MAX_DAYS)
    Result is quantised to 2 decimal places.

    TBD — REQUIRES SPECIFICATION: exact tolerance and scoring function.
    """
    if ct.settlement_date is None:
        return MatchEvidence(
            rule_id="CS004",
            rule_description="settlement_date within expected window of payment_date",
            matched=False,
            field_name="settlement_date",
            expected_value=f"within {_MAX_DATE_DISTANCE_DAYS} days of {ct.payment_date}",
            observed_value=None,
            score_contribution=_ZERO,
        )

    distance_days = abs((ct.settlement_date - ct.payment_date).days)
    if distance_days > _MAX_DATE_DISTANCE_DAYS:
        score = _ZERO
        matched = False
    else:
        # Linear decay: 1.0 at distance=0, 0.0 at distance=MAX
        raw = Decimal(1) - Decimal(distance_days) / Decimal(_MAX_DATE_DISTANCE_DAYS)
        score = raw.quantize(_TWO_PLACES)
        matched = score > _ZERO

    return MatchEvidence(
        rule_id="CS004",
        rule_description=(
            f"settlement_date within {_MAX_DATE_DISTANCE_DAYS}-day window "
            f"of payment_date (distance={distance_days} days)"
        ),
        matched=matched,
        field_name="settlement_date",
        expected_value=f"within {_MAX_DATE_DISTANCE_DAYS} days of {ct.payment_date}",
        observed_value=str(ct.settlement_date),
        score_contribution=score,
    )


def _score_cs005_ref_presence(ct: CanonicalTransaction) -> MatchEvidence:
    """
    CS005: settlement_ref structural link present.

    1.0 if settlement_ref is present (the structural chain has at least
    the settlement reference even if the bank entry is absent).
    0.0 if settlement is absent (should not be reached, but handled safely).
    """
    present = ct.settlement_ref is not None
    return MatchEvidence(
        rule_id="CS005",
        rule_description="settlement_ref structural link present",
        matched=present,
        field_name="settlement_ref",
        expected_value="<present>",
        observed_value=ct.settlement_ref if present else "<missing>",
        score_contribution=_ONE if present else _ZERO,
    )
