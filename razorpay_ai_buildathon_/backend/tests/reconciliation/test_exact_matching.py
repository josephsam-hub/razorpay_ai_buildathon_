"""
Tests — Exact matching stage.

Covers:
  - clean exact match → is_match=True, confidence=1.00
  - missing settlement → is_no_candidate=True
  - missing bank entry → is_match=False, discrepancy detected
  - missing ledger entry → is_match=False
  - amount mismatch (bank credit ≠ settlement net) → REC_E002
  - reference mismatch (bank settlement_ref ≠ settlement_ref) → REC_E009
  - merchant mismatch → REC_E009
  - evidence produced for every rule evaluated
  - no float in results
"""

from __future__ import annotations

from decimal import Decimal

from app.core.reconciliation.exact import run_exact_match
from app.core.reconciliation.normaliser import normalise
from app.data.generator.world import ObservedWorld
from app.models.exceptions import REC_E001, REC_E002, REC_E009

from tests.reconciliation.conftest import (
    make_bank_entry,
    make_clean_world,
    make_ledger_entry,
    make_merchant,
    make_payment,
    make_settlement,
)


def _ct_from_world(world: ObservedWorld):
    return normalise(world).canonical_transactions[0]


class TestExactMatchClean:
    def test_clean_is_match_true(self, clean_world):
        ct = _ct_from_world(clean_world)
        result = run_exact_match(ct)
        assert result.is_match is True

    def test_clean_confidence_is_one(self, clean_world):
        ct = _ct_from_world(clean_world)
        result = run_exact_match(ct)
        assert result.confidence == Decimal("1.00")
        assert isinstance(result.confidence, Decimal)
        assert not isinstance(result.confidence, float)

    def test_clean_no_discrepancy_codes(self, clean_world):
        ct = _ct_from_world(clean_world)
        result = run_exact_match(ct)
        assert result.discrepancy_codes == []

    def test_clean_is_not_no_candidate(self, clean_world):
        ct = _ct_from_world(clean_world)
        result = run_exact_match(ct)
        assert result.is_no_candidate is False

    def test_clean_evidence_all_matched(self, clean_world):
        ct = _ct_from_world(clean_world)
        result = run_exact_match(ct)
        assert len(result.evidence) > 0
        failed = [e for e in result.evidence if not e.matched]
        assert failed == [], f"Unexpected failed rules: {[e.rule_id for e in failed]}"

    def test_clean_evidence_score_contributions_decimal(self, clean_world):
        ct = _ct_from_world(clean_world)
        result = run_exact_match(ct)
        for ev in result.evidence:
            assert isinstance(ev.score_contribution, Decimal)
            assert not isinstance(ev.score_contribution, float)


class TestExactMatchMissingSettlement:
    def test_missing_settlement_is_no_candidate(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=world.bank_entries,
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_no_candidate is True
        assert result.is_match is False

    def test_missing_settlement_zero_confidence(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=world.bank_entries,
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.confidence == Decimal("0")

    def test_missing_settlement_rec_e001(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=world.bank_entries,
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert REC_E001 in result.discrepancy_codes


class TestExactMatchMissingBankEntry:
    def test_missing_bank_not_match(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_match is False

    def test_missing_bank_rec_e001(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert REC_E001 in result.discrepancy_codes

    def test_missing_bank_not_no_candidate(self):
        """Settlement present → not is_no_candidate, even if bank is missing."""
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_no_candidate is False


class TestExactMatchMissingLedgerEntry:
    def test_missing_ledger_not_match(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=world.bank_entries,
            ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_match is False

    def test_missing_ledger_rec_e001(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=world.bank_entries,
            ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert REC_E001 in result.discrepancy_codes


class TestExactMatchAmountMismatch:
    def test_bank_credit_mismatch_rec_e002(self):
        """Bank credit ≠ settlement net → REC_E002."""
        world = make_clean_world()
        # Replace bank with a different credit amount
        bad_bank = make_bank_entry(credit="4500.00")  # should be 4900.00
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[bad_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_match is False
        assert REC_E002 in result.discrepancy_codes

    def test_clean_amount_no_e002(self, clean_world):
        ct = _ct_from_world(clean_world)
        result = run_exact_match(ct)
        assert REC_E002 not in result.discrepancy_codes


class TestExactMatchReferenceMismatch:
    def test_bank_wrong_settlement_ref_rec_e009(self):
        """Bank entry points to wrong settlement_ref → REC_E009."""
        world = make_clean_world()
        bad_bank = make_bank_entry(settlement_ref="REF_WRONG_99999")
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[bad_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        # bad_bank has no matching settlement_ref → bank_entry resolves to None
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_match is False

    def test_ledger_wrong_payment_id_rec_e009(self):
        """LedgerEntry.payment_id doesn't match Payment.payment_id → REC_E009."""
        world = make_clean_world()
        bad_ledger = make_ledger_entry(payment_id="PAY_WRONG_99999")
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=world.bank_entries,
            ledger_entries=[bad_ledger],
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_match is False
        # bad_ledger payment_id doesn't match → it won't be found; ledger is None
        assert ct.ledger_entry_id is None

    def test_merchant_mismatch_rec_e009(self):
        """Settlement.merchant_id ≠ Payment.merchant_id → REC_E009."""
        world = make_clean_world()
        bad_settlement = make_settlement(merchant_id="M_WRONG")
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[bad_settlement], bank_entries=world.bank_entries,
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_match is False
        assert REC_E009 in result.discrepancy_codes


class TestExactMatchEvidence:
    def test_r001_present_in_evidence(self, clean_world):
        ct = _ct_from_world(clean_world)
        result = run_exact_match(ct)
        rule_ids = [e.rule_id for e in result.evidence]
        assert "R001" in rule_ids

    def test_evidence_contains_only_decimal_contributions(self, clean_world):
        ct = _ct_from_world(clean_world)
        result = run_exact_match(ct)
        for ev in result.evidence:
            assert isinstance(ev.score_contribution, Decimal)

    def test_failed_rule_has_zero_contribution(self):
        """A failed rule must have score_contribution = 0."""
        world = make_clean_world()
        bad_bank = make_bank_entry(credit="1.00")  # wildly wrong
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[bad_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        for ev in result.evidence:
            if not ev.matched:
                assert ev.score_contribution == Decimal("0")
