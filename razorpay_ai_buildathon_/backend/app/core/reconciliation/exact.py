"""
LedgerLens Phase 3 — Exact Matching
=====================================
Stage 1 of the reconciliation cascade.

Exact matching verifies that all structural links between the four layers
(Payment → Settlement → BankEntry → LedgerEntry) are intact and that
financial values are exactly consistent.

RESULT CONTRACT:
  ExactMatchResult.is_match == True
    → ALL structural links present AND ALL financial checks pass.
    → confidence = Decimal("1.00"), decision = "AUTO_MATCH" (pending validation layer)
    → Temporal anomalies are handled separately in validation.py (V001–V004)

  ExactMatchResult.is_match == False
    → At least one structural link is broken or a financial value disagrees.
    → decision = "HUMAN_REVIEW" (discrepancy detected)
    → discrepancy_codes carry reconciliation-layer codes (rec:E001–rec:E010)

  ExactMatchResult.is_no_candidate == True
    → No settlement exists at all for this payment
    → decision = "ABSTAIN" (cannot reconcile — nothing to compare against)

DETERMINISM:
  All comparisons are pure value comparisons (no random, no ordering).
  Decimal arithmetic only for financial checks.

RULES EVALUATED (in fixed order):
  R001  Settlement present for payment
  R002  Bank entry present for settlement
  R003  Ledger entry present for payment
  R004  settlement_ref cross-reference (bank ↔ settlement)
  R005  ledger payment_id cross-reference (ledger ↔ payment)
  R006  ledger settlement_id cross-reference (ledger ↔ settlement)
  R007  Merchant consistency (settlement merchant == payment merchant)
  R008  Currency sanity check — payment currency must be "INR"
        NOTE: Settlement and BankEntry do not carry a currency field in the
        Phase 2 domain models (currency lives on Payment only).
        R008 therefore checks Payment.currency == "INR" as a sanity guard.
        TBD — REQUIRES SPECIFICATION: if currency is added to Settlement/BankEntry,
        this rule must be upgraded to a cross-field comparison.
        This rule is WEAK EVIDENCE: it cannot prevent AUTO_MATCH on its own
        because it only validates the payment side.
  R009  Gross amount check (Fix 3):
        - Single-payment settlement: payment_amount MUST EXACTLY equal
          settlement_gross_amount.
        - Multi-payment settlement: settlement_gross_amount MUST be >= payment_amount
          (full batch-sum check TBD — requires all batch payments).
  R010  Bank credit exactly matches settlement net: bank_credit_amount == settlement_net_amount
  R011  Ledger allocation sanity: allocated_amount <= settlement_net_amount
  R013  Duplicate bank entry guard (Fix 2): if has_duplicate_bank_entry is True,
        an additional rec:E003 (Duplicate transaction) is always flagged and
        exact match is blocked — duplicate bank entries must never AUTO_MATCH.

NOTE — TEMPORAL VALIDATION:
  R012 has been REMOVED from exact matching per approved architecture.
  Temporal validation (V001–V004) now lives entirely in the post-match
  validation layer (validation.py). Exact matching handles only structural
  and financial identity checks.
  Structural confidence (1.00) is preserved independently of temporal anomalies.
  A temporally anomalous but structurally correct match → HUMAN_REVIEW,
  NOT a failed exact match. This is enforced by the engine (engine.py).

FALSE AUTO_MATCH PREVENTION:
  The following situations MUST NOT produce AUTO_MATCH:
  - Any structural link broken (R001–R006 fail)
  - Merchant mismatch (R007)
  - Gross amount does not match (R009 for single-payment)
  - Bank credit ≠ settlement net (R010)
  - Duplicate bank entry present (R013)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.canonical import CanonicalTransaction
from app.models.decisions import MatchEvidence
from app.models.exceptions import (
    REC_E001,
    REC_E002,
    REC_E003,
    REC_E009,
    REC_E010,
)

_ZERO = Decimal("0")
_ONE = Decimal("1.00")


@dataclass
class ExactMatchResult:
    """
    Result of running the exact matching stage against one CanonicalTransaction.

    is_match:        True  → AUTO_MATCH with confidence 1.00
    is_no_candidate: True  → ABSTAIN (no settlement found at all)
    Otherwise:              → HUMAN_REVIEW (discrepancy detected)

    amount_delta:    bank_credit - settlement_net (None if unavailable)
    date_delta_days: settlement_date - payment_date (None if unavailable)
    """

    is_match: bool
    is_no_candidate: bool
    evidence: list[MatchEvidence]
    discrepancy_codes: list[str]
    notes: str
    amount_delta: Decimal | None = None
    date_delta_days: int | None = None

    @property
    def confidence(self) -> Decimal:
        return _ONE if self.is_match else _ZERO


def run_exact_match(ct: CanonicalTransaction) -> ExactMatchResult:
    """
    Run all exact-match rules against one CanonicalTransaction.

    Returns an ExactMatchResult describing pass/fail for every rule and
    the aggregate outcome.

    Never mutates the input.
    """
    evidence: list[MatchEvidence] = []
    discrepancy_codes: list[str] = []
    all_passed = True

    # Compute diagnostic deltas (Fix 7)
    amount_delta: Decimal | None = None
    date_delta_days: int | None = None

    def _rule(
        rule_id: str,
        description: str,
        field_name: str,
        matched: bool,
        expected: str | None,
        observed: str | None,
        fail_code: str | None = None,
    ) -> None:
        nonlocal all_passed
        contrib = _ONE if matched else _ZERO
        evidence.append(
            MatchEvidence(
                rule_id=rule_id,
                rule_description=description,
                matched=matched,
                field_name=field_name,
                expected_value=expected,
                observed_value=observed,
                score_contribution=contrib,
            )
        )
        if not matched:
            all_passed = False
            if fail_code and fail_code not in discrepancy_codes:
                discrepancy_codes.append(fail_code)

    # ------------------------------------------------------------------
    # R001 — Settlement present
    # ------------------------------------------------------------------
    settlement_present = ct.has_settlement
    _rule(
        "R001",
        "Settlement record exists for this payment",
        "settlement_id",
        settlement_present,
        "<present>",
        "<present>" if settlement_present else "<missing>",
        REC_E001 if not settlement_present else None,
    )

    # If no settlement, further rules are unevaluable — short-circuit
    if not settlement_present:
        return ExactMatchResult(
            is_match=False,
            is_no_candidate=True,
            evidence=evidence,
            discrepancy_codes=discrepancy_codes,
            notes="No settlement found for payment — cannot reconcile.",
        )

    # ------------------------------------------------------------------
    # R002 — Bank entry present
    # ------------------------------------------------------------------
    bank_present = ct.has_bank_entry
    _rule(
        "R002",
        "Bank entry exists for the settlement",
        "bank_entry_id",
        bank_present,
        "<present>",
        "<present>" if bank_present else "<missing>",
        REC_E001 if not bank_present else None,
    )

    # ------------------------------------------------------------------
    # R003 — Ledger entry present
    # ------------------------------------------------------------------
    ledger_present = ct.has_ledger_entry
    _rule(
        "R003",
        "Ledger entry exists for this payment",
        "ledger_entry_id",
        ledger_present,
        "<present>",
        "<present>" if ledger_present else "<missing>",
        REC_E001 if not ledger_present else None,
    )

    # ------------------------------------------------------------------
    # R004 — settlement_ref cross-reference (bank ↔ settlement)
    # ------------------------------------------------------------------
    if bank_present:
        ref_match = ct.bank_settlement_ref == ct.settlement_ref
        _rule(
            "R004",
            "BankEntry.settlement_ref matches Settlement.settlement_ref",
            "bank_settlement_ref",
            ref_match,
            ct.settlement_ref,
            ct.bank_settlement_ref,
            REC_E009 if not ref_match else None,
        )

    # ------------------------------------------------------------------
    # R005 — ledger payment_id cross-reference
    # ------------------------------------------------------------------
    if ledger_present:
        ledger_pid_match = ct.ledger_payment_id == ct.payment_id
        _rule(
            "R005",
            "LedgerEntry.payment_id matches Payment.payment_id",
            "ledger_payment_id",
            ledger_pid_match,
            ct.payment_id,
            ct.ledger_payment_id,
            REC_E009 if not ledger_pid_match else None,
        )

    # ------------------------------------------------------------------
    # R006 — ledger settlement_id cross-reference
    # ------------------------------------------------------------------
    if ledger_present:
        ledger_sid_match = ct.ledger_settlement_id == ct.settlement_id
        _rule(
            "R006",
            "LedgerEntry.settlement_id matches Settlement.settlement_id",
            "ledger_settlement_id",
            ledger_sid_match,
            ct.settlement_id,
            ct.ledger_settlement_id,
            REC_E009 if not ledger_sid_match else None,
        )

    # ------------------------------------------------------------------
    # R007 — Merchant consistency
    # ------------------------------------------------------------------
    merchant_match = ct.settlement_merchant_id == ct.merchant_id
    _rule(
        "R007",
        "Settlement.merchant_id matches Payment.merchant_id",
        "settlement_merchant_id",
        merchant_match,
        ct.merchant_id,
        ct.settlement_merchant_id,
        REC_E009 if not merchant_match else None,
    )

    # ------------------------------------------------------------------
    # R008 — Currency sanity (WEAK: payment side only)
    # TBD — REQUIRES SPECIFICATION: cross-field check when currency
    # is added to Settlement/BankEntry models.
    # ------------------------------------------------------------------
    currency_ok = ct.currency == "INR"
    _rule(
        "R008",
        "Payment currency is INR (only supported currency; "
        "cross-field check TBD when Settlement/BankEntry carry currency)",
        "currency",
        currency_ok,
        "INR",
        ct.currency,
        # R008 failure does not block AUTO_MATCH on its own (weak evidence)
        # but logs the anomaly. REC_E005 = Currency mismatch.
        "rec:E005" if not currency_ok else None,
    )

    # ------------------------------------------------------------------
    # R009 — Gross amount check (Fix 3)
    # ------------------------------------------------------------------
    if ct.settlement_gross_amount is not None:
        if ct.is_single_payment_settlement:
            # Single-payment: payment_amount MUST exactly equal gross_amount
            gross_ok = ct.payment_amount == ct.settlement_gross_amount
            description = (
                "Single-payment settlement: payment_amount MUST exactly equal "
                "settlement_gross_amount"
            )
        else:
            # Multi-payment: gross must be >= payment_amount (partial check;
            # full batch-sum requires all batch payments — TBD).
            gross_ok = ct.settlement_gross_amount >= ct.payment_amount
            description = (
                f"Multi-payment settlement ({len(ct.settlement_payment_ids)} payments): "
                "settlement_gross_amount >= payment_amount "
                "(full batch-sum check TBD — requires all batch payments)"
            )

        _rule(
            "R009",
            description,
            "settlement_gross_amount",
            gross_ok,
            str(ct.payment_amount),
            str(ct.settlement_gross_amount),
            REC_E002 if not gross_ok else None,
        )

    # ------------------------------------------------------------------
    # R010 — Bank credit exactly == settlement net (Fix 7: compute amount delta)
    # ------------------------------------------------------------------
    if bank_present and ct.settlement_net_amount is not None:
        credit_match = ct.bank_credit_amount == ct.settlement_net_amount
        # Fix 7: compute amount_delta for EvidenceCard
        amount_delta = ct.bank_credit_amount - ct.settlement_net_amount
        _rule(
            "R010",
            "BankEntry.credit_amount == Settlement.net_amount "
            f"(delta={amount_delta:+})",
            "bank_credit_amount",
            credit_match,
            str(ct.settlement_net_amount),
            str(ct.bank_credit_amount),
            REC_E002 if not credit_match else None,
        )

    # Fix 7: compute date_delta_days for EvidenceCard (informational, not a rule)
    if ct.settlement_date is not None:
        date_delta_days = (ct.settlement_date - ct.payment_date).days

    # ------------------------------------------------------------------
    # R011 — Ledger allocation sanity: allocated <= net
    # ------------------------------------------------------------------
    if ledger_present and ct.settlement_net_amount is not None:
        alloc_ok = ct.allocated_amount <= ct.settlement_net_amount
        _rule(
            "R011",
            "LedgerEntry.allocated_amount <= Settlement.net_amount",
            "allocated_amount",
            alloc_ok,
            f"<= {ct.settlement_net_amount}",
            str(ct.allocated_amount),
            REC_E002 if not alloc_ok else None,
        )

    # ------------------------------------------------------------------
    # R013 — Duplicate bank entry guard (Fix 2)
    # ------------------------------------------------------------------
    if ct.has_duplicate_bank_entry:
        _rule(
            "R013",
            "No duplicate bank entries for this settlement_ref "
            "(Fix 2: duplicate bank entries must never AUTO_MATCH — "
            "the correct entry cannot be determined without human review)",
            "bank_entry_id",
            False,
            "<unique>",
            "<duplicate detected>",
            REC_E003,
        )
    # ------------------------------------------------------------------
    # R014 — Settlement fee contract validation (Phase 3.3)
    # ------------------------------------------------------------------
    from decimal import ROUND_HALF_UP
    if ct.merchant_fee_rate is None or ct.settlement_gross_amount is None:
        # NOT_EVALUABLE: must NOT block AUTO_MATCH, must NOT create an exception, must NOT crash
        _rule(
            "R014",
            "Settlement fee contract compliance (NOT_EVALUABLE: missing fee_rate or gross)",
            "settlement_net_amount",
            True,  # Pass to not block AUTO_MATCH
            f"gross={ct.settlement_gross_amount}, fee_rate={ct.merchant_fee_rate}",
            f"net={ct.settlement_net_amount}",
            None,
        )
    else:
        gross = ct.settlement_gross_amount
        fee_rate = ct.merchant_fee_rate
        observed_net = ct.settlement_net_amount if ct.settlement_net_amount is not None else _ZERO

        expected_fee = (gross * fee_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        expected_net = gross - expected_fee

        matched_r014 = (ct.settlement_net_amount == expected_net)
        delta_r014 = (observed_net - expected_net)

        _rule(
            "R014",
            f"Settlement net matches merchant contract fee rate (expected_fee={expected_fee}, expected_net={expected_net}, delta={delta_r014:+})",
            "settlement_net_amount",
            matched_r014,
            f"gross={gross}, fee_rate={fee_rate}, expected_fee={expected_fee}, expected_net={expected_net}",
            f"observed_net={ct.settlement_net_amount}, delta={delta_r014}, status={'PASS' if matched_r014 else 'FAIL'}",
            REC_E002 if not matched_r014 else None,
        )

    # ------------------------------------------------------------------
    # Aggregate result
    # ------------------------------------------------------------------
    if all_passed:
        return ExactMatchResult(
            is_match=True,
            is_no_candidate=False,
            evidence=evidence,
            discrepancy_codes=[],
            notes="All exact-match rules passed.",
            amount_delta=amount_delta,
            date_delta_days=date_delta_days,
        )

    # Determine whether this is truly no-candidate or a detected discrepancy.
    # is_no_candidate is True only when the settlement is present but both
    # bank AND ledger are absent — nothing to compare financially.
    no_bank_no_ledger = (not bank_present) and (not ledger_present)
    only_missing_code = (
        len(discrepancy_codes) == 1
        and discrepancy_codes[0] == REC_E001
    )
    return ExactMatchResult(
        is_match=False,
        is_no_candidate=no_bank_no_ledger and only_missing_code,
        evidence=evidence,
        discrepancy_codes=discrepancy_codes,
        notes=_build_notes(discrepancy_codes),
        amount_delta=amount_delta,
        date_delta_days=date_delta_days,
    )


def _build_notes(codes: list[str]) -> str:
    descriptions = {
        REC_E001: "missing record(s)",
        REC_E002: "amount mismatch",
        REC_E003: "duplicate transaction",
        "rec:E004": "date-window violation",
        "rec:E005": "currency mismatch",
        REC_E009: "reference mismatch",
        REC_E010: "insufficient evidence",
    }
    parts = [descriptions.get(c, c) for c in codes]
    return "Discrepancies detected: " + ", ".join(parts) if parts else ""
