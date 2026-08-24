"""
Tests — Post-match temporal validation layer (V001–V004).

Architecture note:
  Temporal validation runs AFTER exact structural matching.
  A structurally matched transaction with a temporal anomaly → HUMAN_REVIEW.
  A structurally matched transaction with clean validation → AUTO_MATCH.
  Temporal anomalies do NOT destroy the structural relationship.
  Confidence remains 1.00 (structural); decision becomes HUMAN_REVIEW.

Covers:
  V001 — settlement_date >= latest_payment_date_in_settlement
  V002 — settlement_date == latest_payment_date + settlement_cycle_days
  V003 — 0 <= value_date - settlement_date <= 1 day
  V004 — 0 <= posting_date - value_date <= 2 days
  Engine integration — structural match + temporal anomaly → HUMAN_REVIEW
  Engine integration — structural match + clean validation → AUTO_MATCH
  Multi-payment batch — latest_payment_date used as anchor, not this payment's date
  Candidate-specific — validation only runs on records present in CT
  Determinism — identical input produces identical findings
  ValidationFinding fields — rule_id, severity, delta, affected_record_ids, discrepancy_code
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.reconciliation.normaliser import normalise
from app.core.reconciliation.validation import run_validation
from app.data.generator.world import ObservedWorld
from app.models.canonical import CanonicalTransaction
from app.models.exceptions import REC_E004
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

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ct(world: ObservedWorld) -> CanonicalTransaction:
    return normalise(world).canonical_transactions[0]


def _svc():
    return ReconciliationService()


def _make_ct(**overrides) -> CanonicalTransaction:
    """Build a minimal CanonicalTransaction for direct validation testing."""
    defaults = dict(
        payment_id="PAY_20260801_00001",
        merchant_id="M_001",
        payment_amount=Decimal("5000.00"),
        currency="INR",
        payment_date=date(2026, 8, 1),
        gateway_ref="RPY_GW_90001",
        settlement_id="SET_20260802_0001",
        settlement_ref="REF_SET_00001",
        settlement_date=date(2026, 8, 2),
        settlement_gross_amount=Decimal("5000.00"),
        settlement_fee_amount=Decimal("100.00"),
        settlement_net_amount=Decimal("4900.00"),
        settlement_merchant_id="M_001",
        settlement_payment_ids=["PAY_20260801_00001"],
        latest_payment_date_in_settlement=date(2026, 8, 1),
        settlement_cycle_days=1,
        bank_entry_id="BNK_20260802_0001",
        bank_ref="UTR_10001",
        bank_settlement_ref="REF_SET_00001",
        bank_credit_amount=Decimal("4900.00"),
        value_date=date(2026, 8, 2),
        ledger_entry_id="LED_20260802_0001",
        ledger_payment_id="PAY_20260801_00001",
        ledger_settlement_id="SET_20260802_0001",
        ledger_bank_entry_id="BNK_20260802_0001",
        allocated_amount=Decimal("4900.00"),
        posting_date=date(2026, 8, 2),
    )
    defaults.update(overrides)
    return CanonicalTransaction(**defaults)


# ── V001 — Settlement Cause ───────────────────────────────────────────────────

class TestV001SettlementCause:
    def test_v001_passes_when_settlement_date_after_latest_payment(self):
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 1),
            settlement_date=date(2026, 8, 2),
        )
        findings = run_validation(ct)
        v001 = next(f for f in findings if f.rule_id == "V001")
        assert v001.passed is True
        assert v001.discrepancy_code is None

    def test_v001_passes_when_settlement_date_equals_latest_payment(self):
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 2),
            settlement_date=date(2026, 8, 2),
        )
        findings = run_validation(ct)
        v001 = next(f for f in findings if f.rule_id == "V001")
        assert v001.passed is True

    def test_v001_fails_when_settlement_before_latest_payment(self):
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 5),
            settlement_date=date(2026, 8, 2),  # BEFORE latest payment
        )
        findings = run_validation(ct)
        v001 = next(f for f in findings if f.rule_id == "V001")
        assert v001.passed is False
        assert v001.discrepancy_code == REC_E004

    def test_v001_delta_negative_when_settlement_before_latest(self):
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 5),
            settlement_date=date(2026, 8, 2),
        )
        findings = run_validation(ct)
        v001 = next(f for f in findings if f.rule_id == "V001")
        assert v001.delta is not None
        assert "-" in v001.delta  # negative delta

    def test_v001_affected_record_ids_contains_payment_and_settlement(self):
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 5),
            settlement_date=date(2026, 8, 2),
        )
        findings = run_validation(ct)
        v001 = next(f for f in findings if f.rule_id == "V001")
        assert "PAY_20260801_00001" in v001.affected_record_ids
        assert "SET_20260802_0001" in v001.affected_record_ids

    def test_v001_not_evaluated_when_settlement_absent(self):
        ct = _make_ct(
            settlement_id=None,
            settlement_ref=None,
            settlement_date=None,
            settlement_gross_amount=None,
            settlement_fee_amount=None,
            settlement_net_amount=None,
            settlement_merchant_id=None,
            settlement_payment_ids=[],
            latest_payment_date_in_settlement=None,
            settlement_cycle_days=None,
        )
        findings = run_validation(ct)
        rule_ids = [f.rule_id for f in findings]
        assert "V001" not in rule_ids

    def test_v001_severity_is_error(self):
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 5),
            settlement_date=date(2026, 8, 2),
        )
        findings = run_validation(ct)
        v001 = next(f for f in findings if f.rule_id == "V001")
        assert v001.severity == "ERROR"


# ── V002 — Settlement Cycle ───────────────────────────────────────────────────

class TestV002SettlementCycle:
    def test_v002_passes_exact_cycle(self):
        """settlement_date == latest_payment_date + cycle_days."""
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 1),
            settlement_cycle_days=1,
            settlement_date=date(2026, 8, 2),  # 1 + 1 = 2
        )
        findings = run_validation(ct)
        v002 = next(f for f in findings if f.rule_id == "V002")
        assert v002.passed is True
        assert v002.discrepancy_code is None

    def test_v002_fails_cycle_mismatch(self):
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 1),
            settlement_cycle_days=1,
            settlement_date=date(2026, 8, 5),  # expected 2026-08-02
        )
        findings = run_validation(ct)
        v002 = next(f for f in findings if f.rule_id == "V002")
        assert v002.passed is False
        assert v002.discrepancy_code == REC_E004

    def test_v002_delta_shows_deviation_in_days(self):
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 1),
            settlement_cycle_days=1,
            settlement_date=date(2026, 8, 5),
        )
        findings = run_validation(ct)
        v002 = next(f for f in findings if f.rule_id == "V002")
        # Delta = 2026-08-05 - 2026-08-02 = +3 days
        assert "+3" in v002.delta

    def test_v002_uses_latest_payment_date_as_anchor(self):
        """For multi-payment batches, V002 anchor is latest_payment_date, not this payment's date."""
        ct = _make_ct(
            payment_date=date(2026, 8, 1),               # this payment
            latest_payment_date_in_settlement=date(2026, 8, 8),  # latest in batch
            settlement_cycle_days=2,
            settlement_date=date(2026, 8, 10),            # 8 + 2 = 10 ✓
            settlement_payment_ids=["PAY_A", "PAY_B", "PAY_20260801_00001"],
        )
        findings = run_validation(ct)
        v002 = next(f for f in findings if f.rule_id == "V002")
        assert v002.passed is True

    def test_v002_severity_is_warning(self):
        """V002 is WARNING (cycle deviation), not ERROR (settlement before payment)."""
        ct = _make_ct(
            latest_payment_date_in_settlement=date(2026, 8, 1),
            settlement_cycle_days=1,
            settlement_date=date(2026, 8, 5),
        )
        findings = run_validation(ct)
        v002 = next(f for f in findings if f.rule_id == "V002")
        assert v002.severity == "WARNING"

    def test_v002_not_evaluated_without_cycle_days(self):
        ct = _make_ct(settlement_cycle_days=None)
        findings = run_validation(ct)
        rule_ids = [f.rule_id for f in findings]
        assert "V002" not in rule_ids


# ── V003 — Bank Timing ────────────────────────────────────────────────────────

class TestV003BankTiming:
    def test_v003_passes_same_day(self):
        ct = _make_ct(
            settlement_date=date(2026, 8, 2),
            value_date=date(2026, 8, 2),  # 0 days
        )
        findings = run_validation(ct)
        v003 = next(f for f in findings if f.rule_id == "V003")
        assert v003.passed is True

    def test_v003_passes_one_day_after(self):
        ct = _make_ct(
            settlement_date=date(2026, 8, 2),
            value_date=date(2026, 8, 3),  # +1 day
        )
        findings = run_validation(ct)
        v003 = next(f for f in findings if f.rule_id == "V003")
        assert v003.passed is True

    def test_v003_fails_two_days_after(self):
        ct = _make_ct(
            settlement_date=date(2026, 8, 2),
            value_date=date(2026, 8, 4),  # +2 days — outside window
        )
        findings = run_validation(ct)
        v003 = next(f for f in findings if f.rule_id == "V003")
        assert v003.passed is False
        assert v003.discrepancy_code == REC_E004

    def test_v003_fails_bank_before_settlement(self):
        ct = _make_ct(
            settlement_date=date(2026, 8, 3),
            value_date=date(2026, 8, 2),  # -1 day (before settlement)
        )
        findings = run_validation(ct)
        v003 = next(f for f in findings if f.rule_id == "V003")
        assert v003.passed is False

    def test_v003_delta_in_days(self):
        ct = _make_ct(
            settlement_date=date(2026, 8, 2),
            value_date=date(2026, 8, 4),
        )
        findings = run_validation(ct)
        v003 = next(f for f in findings if f.rule_id == "V003")
        assert "+2" in v003.delta

    def test_v003_not_evaluated_when_bank_absent(self):
        ct = _make_ct(
            bank_entry_id=None,
            bank_ref=None,
            bank_settlement_ref=None,
            bank_credit_amount=None,
            value_date=None,
        )
        findings = run_validation(ct)
        rule_ids = [f.rule_id for f in findings]
        assert "V003" not in rule_ids

    def test_v003_affected_record_ids_contains_settlement_and_bank(self):
        ct = _make_ct(
            settlement_date=date(2026, 8, 2),
            value_date=date(2026, 8, 4),
        )
        findings = run_validation(ct)
        v003 = next(f for f in findings if f.rule_id == "V003")
        assert "SET_20260802_0001" in v003.affected_record_ids
        assert "BNK_20260802_0001" in v003.affected_record_ids


# ── V004 — Ledger Timing ──────────────────────────────────────────────────────

class TestV004LedgerTiming:
    def test_v004_passes_same_day(self):
        ct = _make_ct(
            value_date=date(2026, 8, 2),
            posting_date=date(2026, 8, 2),
        )
        findings = run_validation(ct)
        v004 = next(f for f in findings if f.rule_id == "V004")
        assert v004.passed is True

    def test_v004_passes_two_days_after(self):
        ct = _make_ct(
            value_date=date(2026, 8, 2),
            posting_date=date(2026, 8, 4),  # +2 days (boundary)
        )
        findings = run_validation(ct)
        v004 = next(f for f in findings if f.rule_id == "V004")
        assert v004.passed is True

    def test_v004_fails_three_days_after(self):
        ct = _make_ct(
            value_date=date(2026, 8, 2),
            posting_date=date(2026, 8, 5),  # +3 days — outside window
        )
        findings = run_validation(ct)
        v004 = next(f for f in findings if f.rule_id == "V004")
        assert v004.passed is False
        assert v004.discrepancy_code == REC_E004

    def test_v004_fails_ledger_before_bank(self):
        ct = _make_ct(
            value_date=date(2026, 8, 3),
            posting_date=date(2026, 8, 2),  # before bank entry
        )
        findings = run_validation(ct)
        v004 = next(f for f in findings if f.rule_id == "V004")
        assert v004.passed is False

    def test_v004_not_evaluated_when_ledger_absent(self):
        ct = _make_ct(
            ledger_entry_id=None,
            ledger_payment_id=None,
            ledger_settlement_id=None,
            ledger_bank_entry_id=None,
            allocated_amount=None,
            posting_date=None,
        )
        findings = run_validation(ct)
        rule_ids = [f.rule_id for f in findings]
        assert "V004" not in rule_ids


# ── Engine integration — structural match + temporal anomaly ──────────────────

class TestEngineTemporalIntegration:
    def test_structurally_matched_with_temporal_anomaly_gives_human_review(self):
        """
        A transaction that passes all structural checks but fails V001
        (settlement before latest payment) must produce HUMAN_REVIEW,
        not AUTO_MATCH.
        The structural confidence must remain 1.00.
        """
        from app.data.generator.models import Settlement, BankEntry, LedgerEntry
        merchant = make_merchant()
        payment = make_payment()
        # Settlement dated BEFORE payment — triggers V001
        bad_settlement = Settlement(
            settlement_id="SET_20260731_0001",
            merchant_id="M_001",
            payment_ids=["PAY_20260801_00001"],
            settlement_date=date(2026, 7, 31),  # BEFORE payment_date 2026-08-01
            gross_amount=Decimal("5000.00"),
            fee_amount=Decimal("100.00"),
            net_amount=Decimal("4900.00"),
            settlement_ref="REF_SET_00001",
        )
        # Bank entry consistent with this bad settlement
        bank = make_bank_entry(settlement_ref="REF_SET_00001", credit="4900.00",
                               value_date=date(2026, 7, 31))
        # Ledger entry consistent with this bad settlement
        ledger = make_ledger_entry(
            settlement_id="SET_20260731_0001",
            bank_entry_id=bank.bank_entry_id,
            posting_date=date(2026, 7, 31),
        )
        world = ObservedWorld(
            merchants=[merchant],
            payments=[payment],
            settlements=[bad_settlement],
            bank_entries=[bank],
            ledger_entries=[ledger],
            ground_truth=[],
            corruption_events=[],
        )
        result, exceptions = _svc().reconcile(world, now=FIXED_NOW)
        d = result.decisions[0]
        card = result.evidence_cards[0]

        # Decision must be HUMAN_REVIEW due to temporal anomaly
        assert d.decision == "HUMAN_REVIEW"
        # Structural confidence must remain 1.00 (structural match was exact)
        assert d.confidence == Decimal("1.00")
        # EvidenceCard must carry the validation findings
        assert any(f.rule_id == "V001" for f in card.validation_findings)
        # Exception must be created
        assert len(exceptions) == 1
        assert REC_E004 in exceptions[0].exception_codes

    def test_structurally_matched_clean_validation_gives_auto_match(self, clean_world):
        """A clean transaction (passing all structural + temporal checks) → AUTO_MATCH."""
        result, exceptions = _svc().reconcile(clean_world, now=FIXED_NOW)
        assert result.decisions[0].decision == "AUTO_MATCH"
        assert result.decisions[0].confidence == Decimal("1.00")
        assert exceptions == []

    def test_temporal_anomaly_does_not_destroy_matched_ids(self):
        """HUMAN_REVIEW from temporal anomaly must still carry the matched record IDs."""
        from app.data.generator.models import Settlement
        merchant = make_merchant()
        payment = make_payment()
        bad_settlement = Settlement(
            settlement_id="SET_20260731_0001",
            merchant_id="M_001",
            payment_ids=["PAY_20260801_00001"],
            settlement_date=date(2026, 7, 31),
            gross_amount=Decimal("5000.00"),
            fee_amount=Decimal("100.00"),
            net_amount=Decimal("4900.00"),
            settlement_ref="REF_SET_00001",
        )
        bank = make_bank_entry(settlement_ref="REF_SET_00001", credit="4900.00",
                               value_date=date(2026, 7, 31))
        ledger = make_ledger_entry(
            settlement_id="SET_20260731_0001",
            bank_entry_id=bank.bank_entry_id,
            posting_date=date(2026, 7, 31),
        )
        world = ObservedWorld(
            merchants=[merchant], payments=[payment],
            settlements=[bad_settlement], bank_entries=[bank],
            ledger_entries=[ledger], ground_truth=[], corruption_events=[],
        )
        result, _ = _svc().reconcile(world, now=FIXED_NOW)
        card = result.evidence_cards[0]
        # Structural relationship is preserved even though temporal validation failed
        assert card.matched_settlement_id is not None
        assert card.matched_bank_entry_id is not None

    def test_temporal_anomaly_v001_sets_rec_e004(self):
        """V001 failure must produce rec:E004 in exception codes."""
        from app.data.generator.models import Settlement
        merchant = make_merchant()
        payment = make_payment()
        bad_settlement = Settlement(
            settlement_id="SET_20260731_0001",
            merchant_id="M_001",
            payment_ids=["PAY_20260801_00001"],
            settlement_date=date(2026, 7, 31),
            gross_amount=Decimal("5000.00"),
            fee_amount=Decimal("100.00"),
            net_amount=Decimal("4900.00"),
            settlement_ref="REF_SET_00001",
        )
        bank = make_bank_entry(settlement_ref="REF_SET_00001", credit="4900.00",
                               value_date=date(2026, 7, 31))
        ledger = make_ledger_entry(
            settlement_id="SET_20260731_0001",
            bank_entry_id=bank.bank_entry_id,
            posting_date=date(2026, 7, 31),
        )
        world = ObservedWorld(
            merchants=[merchant], payments=[payment],
            settlements=[bad_settlement], bank_entries=[bank],
            ledger_entries=[ledger], ground_truth=[], corruption_events=[],
        )
        result, _ = _svc().reconcile(world, now=FIXED_NOW)
        d = result.decisions[0]
        assert REC_E004 in d.exception_codes


# ── Validation is candidate-specific ─────────────────────────────────────────

class TestValidationCandidateSpecific:
    def test_v001_not_run_when_no_settlement(self):
        ct = _make_ct(
            settlement_id=None, settlement_ref=None, settlement_date=None,
            settlement_gross_amount=None, settlement_fee_amount=None,
            settlement_net_amount=None, settlement_merchant_id=None,
            settlement_payment_ids=[], latest_payment_date_in_settlement=None,
            settlement_cycle_days=None,
        )
        findings = run_validation(ct)
        # V001 and V002 require settlement — they must not run
        rule_ids = [f.rule_id for f in findings]
        assert "V001" not in rule_ids
        assert "V002" not in rule_ids
        # V003 requires both settlement and bank — must not run either
        assert "V003" not in rule_ids

    def test_v003_not_run_when_bank_absent(self):
        ct = _make_ct(
            bank_entry_id=None, bank_ref=None, bank_settlement_ref=None,
            bank_credit_amount=None, value_date=None,
        )
        findings = run_validation(ct)
        rule_ids = [f.rule_id for f in findings]
        assert "V003" not in rule_ids

    def test_v004_not_run_when_ledger_absent(self):
        ct = _make_ct(
            ledger_entry_id=None, ledger_payment_id=None,
            ledger_settlement_id=None, ledger_bank_entry_id=None,
            allocated_amount=None, posting_date=None,
        )
        findings = run_validation(ct)
        rule_ids = [f.rule_id for f in findings]
        assert "V004" not in rule_ids


# ── Determinism ───────────────────────────────────────────────────────────────

class TestValidationDeterminism:
    def test_same_ct_produces_identical_findings(self, clean_world):
        ct = normalise(clean_world).canonical_transactions[0]
        findings_a = run_validation(ct)
        findings_b = run_validation(ct)
        assert [(f.rule_id, f.passed, f.delta) for f in findings_a] == \
               [(f.rule_id, f.passed, f.delta) for f in findings_b]

    def test_clean_world_all_validation_findings_pass(self, clean_world):
        ct = normalise(clean_world).canonical_transactions[0]
        findings = run_validation(ct)
        # All findings must pass for a clean, fully-linked world
        failed = [f for f in findings if not f.passed]
        assert failed == [], f"Unexpected failures: {[f.rule_id for f in failed]}"

    def test_multi_payment_settlement_uses_latest_date(self):
        """
        For a multi-payment batch, V001 and V002 use latest_payment_date,
        not this specific payment's date.
        """
        ct = _make_ct(
            payment_date=date(2026, 8, 1),
            latest_payment_date_in_settlement=date(2026, 8, 5),
            settlement_cycle_days=2,
            settlement_date=date(2026, 8, 7),  # 5 + 2 = 7 ✓
            settlement_payment_ids=["PAY_A", "PAY_B", "PAY_20260801_00001"],
        )
        findings = run_validation(ct)
        v001 = next(f for f in findings if f.rule_id == "V001")
        v002 = next(f for f in findings if f.rule_id == "V002")
        assert v001.passed is True
        assert v002.passed is True
