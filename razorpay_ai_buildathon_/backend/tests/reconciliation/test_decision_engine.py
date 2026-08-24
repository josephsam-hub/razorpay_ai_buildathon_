"""
Tests — Decision engine and per-payment reconciliation.

Covers:
  - AUTO_MATCH on clean exact match
  - HUMAN_REVIEW on detected discrepancy with composite evidence
  - ABSTAIN on no settlement
  - AGENT_REVIEW never appears in output (Phase 4 only)
  - EvidenceCard shape
  - ExceptionRecord created for non-AUTO_MATCH
  - confidence is Decimal
  - confidence = 1.00 on AUTO_MATCH
  - audit_id format
  - processed_at does not affect decision
  - input immutability
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.reconciliation.engine import reconcile_batch
from app.core.reconciliation.normaliser import normalise
from app.data.generator.world import ObservedWorld
from app.services.reconciliation import ReconciliationService

from tests.reconciliation.conftest import (
    FIXED_NOW,
    make_bank_entry,
    make_clean_world,
    make_ledger_entry,
    make_payment,
    make_settlement,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reconcile(world: ObservedWorld, now=FIXED_NOW):
    canonical = normalise(world).canonical_transactions
    return reconcile_batch(canonical, batch_id="TEST_BATCH", now=now)


class TestAutoMatch:
    def test_clean_world_produces_auto_match(self, clean_world):
        result, _ = _reconcile(clean_world)
        assert result.decisions[0].decision == "AUTO_MATCH"

    def test_auto_match_confidence_is_one(self, clean_world):
        result, _ = _reconcile(clean_world)
        d = result.decisions[0]
        assert d.confidence == Decimal("1.00")
        assert isinstance(d.confidence, Decimal)

    def test_auto_match_no_exception_codes(self, clean_world):
        result, _ = _reconcile(clean_world)
        assert result.decisions[0].exception_codes == []

    def test_auto_match_evidence_card_has_matched_ids(self, clean_world):
        result, _ = _reconcile(clean_world)
        card = result.evidence_cards[0]
        assert card.matched_settlement_id is not None
        assert card.matched_bank_entry_id is not None
        assert card.matched_ledger_entry_id is not None

    def test_auto_match_produces_no_exception_record(self, clean_world):
        _, exceptions = _reconcile(clean_world)
        assert exceptions == []

    def test_auto_match_stage_reached_exact(self, clean_world):
        result, _ = _reconcile(clean_world)
        card = result.evidence_cards[0]
        assert card.stage_reached == "exact"


class TestHumanReview:
    def _world_with_missing_bank(self):
        world = make_clean_world()
        return ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )

    def test_missing_bank_produces_human_review_or_abstain(self):
        """Missing bank entry → not AUTO_MATCH."""
        world = self._world_with_missing_bank()
        result, _ = _reconcile(world)
        assert result.decisions[0].decision in ("HUMAN_REVIEW", "ABSTAIN")

    def test_amount_mismatch_produces_human_review(self):
        world = make_clean_world()
        bad_bank = make_bank_entry(credit="1.00")  # wrong amount
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[bad_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        result, _ = _reconcile(world)
        # Exact match fails (R010), composite has_any_signal is True (CS001,CS002,CS005)
        # → HUMAN_REVIEW
        assert result.decisions[0].decision == "HUMAN_REVIEW"

    def test_human_review_produces_exception_record(self):
        world = make_clean_world()
        bad_bank = make_bank_entry(credit="1.00")
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[bad_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        _, exceptions = _reconcile(world)
        assert len(exceptions) == 1
        assert exceptions[0].payment_id == "PAY_20260801_00001"

    def test_human_review_exception_status_detected(self):
        world = make_clean_world()
        bad_bank = make_bank_entry(credit="1.00")
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[bad_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        _, exceptions = _reconcile(world)
        assert exceptions[0].status == "DETECTED"

    def test_human_review_confidence_below_one(self):
        world = make_clean_world()
        bad_bank = make_bank_entry(credit="1.00")
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[bad_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        result, _ = _reconcile(world)
        assert result.decisions[0].confidence < Decimal("1.00")


class TestAbstain:
    def test_no_settlement_produces_abstain(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=[],
            ledger_entries=[], ground_truth=[], corruption_events=[],
        )
        result, _ = _reconcile(world)
        assert result.decisions[0].decision == "ABSTAIN"

    def test_abstain_confidence_is_zero(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=[],
            ledger_entries=[], ground_truth=[], corruption_events=[],
        )
        result, _ = _reconcile(world)
        assert result.decisions[0].confidence == Decimal("0")

    def test_abstain_produces_exception_record(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=[],
            ledger_entries=[], ground_truth=[], corruption_events=[],
        )
        _, exceptions = _reconcile(world)
        assert len(exceptions) == 1

    def test_abstain_matched_ids_are_none(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=[],
            ledger_entries=[], ground_truth=[], corruption_events=[],
        )
        result, _ = _reconcile(world)
        card = result.evidence_cards[0]
        assert card.matched_settlement_id is None
        assert card.matched_bank_entry_id is None
        assert card.matched_ledger_entry_id is None


class TestNoAgentReview:
    def test_agent_review_never_in_output(self, clean_world):
        """AGENT_REVIEW must never appear — Phase 4 only."""
        result, _ = _reconcile(clean_world)
        for d in result.decisions:
            assert d.decision != "AGENT_REVIEW"

    def test_agent_review_never_in_evidence_cards(self, clean_world):
        result, _ = _reconcile(clean_world)
        for card in result.evidence_cards:
            assert card.decision != "AGENT_REVIEW"


class TestEvidenceCard:
    def test_evidence_card_has_audit_id(self, clean_world):
        result, _ = _reconcile(clean_world)
        card = result.evidence_cards[0]
        assert card.audit_id.startswith("AUD_")

    def test_evidence_card_has_payment_id(self, clean_world):
        result, _ = _reconcile(clean_world)
        card = result.evidence_cards[0]
        assert card.payment_id == "PAY_20260801_00001"

    def test_evidence_card_confidence_is_decimal(self, clean_world):
        result, _ = _reconcile(clean_world)
        card = result.evidence_cards[0]
        assert isinstance(card.confidence, Decimal)
        assert not isinstance(card.confidence, float)

    def test_evidence_card_decision_matches_decision_model(self, clean_world):
        result, _ = _reconcile(clean_world)
        card = result.evidence_cards[0]
        decision = result.decisions[0]
        assert card.decision == decision.decision

    def test_evidence_card_has_evidence_list(self, clean_world):
        result, _ = _reconcile(clean_world)
        card = result.evidence_cards[0]
        assert isinstance(card.evidence, list)
        assert len(card.evidence) > 0

    def test_evidence_card_processed_at_does_not_affect_decision(self, clean_world):
        """Calling reconcile twice with different timestamps gives same decision."""
        t1 = datetime(2026, 8, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 12, 31, tzinfo=timezone.utc)
        r1, _ = _reconcile(clean_world, now=t1)
        r2, _ = _reconcile(clean_world, now=t2)
        assert r1.decisions[0].decision == r2.decisions[0].decision
        assert r1.decisions[0].confidence == r2.decisions[0].confidence


class TestInputImmutability:
    def test_world_not_mutated_by_reconciliation(self, clean_world):
        original_payment_amount = clean_world.payments[0].amount
        original_settlement_net = clean_world.settlements[0].net_amount
        _reconcile(clean_world)
        assert clean_world.payments[0].amount == original_payment_amount
        assert clean_world.settlements[0].net_amount == original_settlement_net
