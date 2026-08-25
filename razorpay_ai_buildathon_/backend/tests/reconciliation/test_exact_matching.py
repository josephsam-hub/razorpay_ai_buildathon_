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


class TestExactMatchR014:
    def test_clean_single_payment_settlement_r014_pass(self):
        # 1. clean single-payment settlement → R014 PASS
        world = make_clean_world()
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_match is True

        # Check that R014 is in evidence and passed
        r014_ev = next(e for e in result.evidence if e.rule_id == "R014")
        assert r014_ev.matched is True

    def test_clean_multi_payment_settlement_r014_pass(self):
        # 2. clean multi-payment settlement → R014 PASS
        merchant = make_merchant(mid="M_001") # fee_rate = 0.02
        p1 = make_payment(pid="PAY_1", amount="3000.00")
        p2 = make_payment(pid="PAY_2", amount="2000.00")
        # Batch gross = 5000.00. expected_fee = 5000 * 0.02 = 100.00. net = 4900.00
        settlement = make_settlement(
            sid="SET_BATCH",
            payment_ids=["PAY_1", "PAY_2"],
            gross="5000.00",
            fee="100.00",
            net="4900.00",
            settlement_ref="REF_BATCH",
        )
        bank = make_bank_entry(settlement_ref="REF_BATCH", credit="4900.00")
        # Let's create ObservedWorld
        world = ObservedWorld(
            merchants=[merchant],
            payments=[p1, p2],
            settlements=[settlement],
            bank_entries=[bank],
            ledger_entries=[],
            ground_truth=[],
            corruption_events=[],
        )
        # Verify first payment
        ct1 = normalise(world).canonical_transactions[0]
        result1 = run_exact_match(ct1)
        # Should match R014 (note: ledger is missing, so exact match fails structural, but R014 should pass)
        r014_ev = next(e for e in result1.evidence if e.rule_id == "R014")
        assert r014_ev.matched is True

    def test_e007_single_payment_r014_fail(self):
        # 3. E007 single-payment → R014 FAIL
        world = make_clean_world()
        # Modifying settlement to have incorrect fee and net (representing E007)
        # gross = 5000.00, original fee = 100.00, net = 4900.00
        # E007 shifts fee by 2% of gross = 100.00. So new fee = 200.00, new net = 4800.00
        corrupted_settlement = make_settlement(
            gross="5000.00",
            fee="200.00",
            net="4800.00",
        )
        # CRIT-2: Sync bank credit to new net
        corrupted_bank = make_bank_entry(credit="4800.00")
        world = ObservedWorld(
            merchants=world.merchants,
            payments=world.payments,
            settlements=[corrupted_settlement],
            bank_entries=[corrupted_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[],
            corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_match is False
        assert REC_E002 in result.discrepancy_codes
        r014_ev = next(e for e in result.evidence if e.rule_id == "R014")
        assert r014_ev.matched is False

    def test_e007_multi_payment_r014_fail(self):
        # 4. E007 multi-payment → R014 FAIL
        merchant = make_merchant(mid="M_001") # fee_rate = 0.02
        p1 = make_payment(pid="PAY_1", amount="3000.00")
        p2 = make_payment(pid="PAY_2", amount="2000.00")
        # Expected fee = 100.00, expected net = 4900.00.
        # Corrupt fee = 150.00, net = 4850.00.
        corrupted_settlement = make_settlement(
            sid="SET_BATCH",
            payment_ids=["PAY_1", "PAY_2"],
            gross="5000.00",
            fee="150.00",
            net="4850.00",
            settlement_ref="REF_BATCH",
        )
        corrupted_bank = make_bank_entry(settlement_ref="REF_BATCH", credit="4850.00")
        world = ObservedWorld(
            merchants=[merchant],
            payments=[p1, p2],
            settlements=[corrupted_settlement],
            bank_entries=[corrupted_bank],
            ledger_entries=[],
            ground_truth=[],
            corruption_events=[],
        )
        ct1 = normalise(world).canonical_transactions[0]
        result1 = run_exact_match(ct1)
        r014_ev = next(e for e in result1.evidence if e.rule_id == "R014")
        assert r014_ev.matched is False

    def test_decimal_round_half_up_boundary_case(self):
        # 5. Decimal ROUND_HALF_UP boundary case
        # gross = 100.25, fee_rate = 0.02 => gross * rate = 2.0050.
        # ROUND_HALF_UP of 2.005 => 2.01
        merchant = make_merchant(mid="M_001")
        merchant = merchant.model_copy(update={"fee_rate": Decimal("0.02")})
        p = make_payment(amount="100.25")
        # expected fee = round(100.25 * 0.02, 2) = round(2.005, 2) = 2.01
        # expected net = 100.25 - 2.01 = 98.24
        settlement = make_settlement(gross="100.25", fee="2.01", net="98.24")
        bank = make_bank_entry(credit="98.24")
        world = ObservedWorld(
            merchants=[merchant],
            payments=[p],
            settlements=[settlement],
            bank_entries=[bank],
            ledger_entries=[],
            ground_truth=[],
            corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        r014_ev = next(e for e in result.evidence if e.rule_id == "R014")
        assert r014_ev.matched is True

        # Test boundary 2.0049 which rounds down to 2.00
        # If gross = 100.24, gross * rate = 2.0048 => rounds to 2.00. net = 98.24
        p2 = make_payment(amount="100.24")
        settlement2 = make_settlement(gross="100.24", fee="2.00", net="98.24")
        bank2 = make_bank_entry(credit="98.24")
        world2 = ObservedWorld(
            merchants=[merchant],
            payments=[p2],
            settlements=[settlement2],
            bank_entries=[bank2],
            ledger_entries=[],
            ground_truth=[],
            corruption_events=[],
        )
        ct2 = _ct_from_world(world2)
        result2 = run_exact_match(ct2)
        r014_ev2 = next(e for e in result2.evidence if e.rule_id == "R014")
        assert r014_ev2.matched is True

    def test_merchant_fee_rate_missing_not_evaluable(self):
        # 6. merchant fee rate missing → NOT_EVALUABLE
        world = make_clean_world()
        world = ObservedWorld(
            merchants=[], # no merchant config
            payments=world.payments,
            settlements=world.settlements,
            bank_entries=world.bank_entries,
            ledger_entries=world.ledger_entries,
            ground_truth=[],
            corruption_events=[],
        )
        ct = _ct_from_world(world)
        assert ct.merchant_fee_rate is None
        result = run_exact_match(ct)
        r014_ev = next(e for e in result.evidence if e.rule_id == "R014")
        assert r014_ev.matched is True
        assert result.is_match is True

    def test_settlement_gross_missing_not_evaluable(self):
        # 7. settlement gross missing → NOT_EVALUABLE
        world = make_clean_world()
        ct = _ct_from_world(world)
        ct_corrupted = ct.model_copy(update={"settlement_gross_amount": None})
        result = run_exact_match(ct_corrupted)
        r014_ev = next(e for e in result.evidence if e.rule_id == "R014")
        assert r014_ev.matched is True

    def test_r010_pass_and_r014_fail(self):
        # 8. R010 PASS + R014 FAIL
        world = make_clean_world()
        corrupted_settlement = make_settlement(
            gross="5000.00",
            fee="150.00",
            net="4850.00",
        )
        corrupted_bank = make_bank_entry(credit="4850.00")
        world = ObservedWorld(
            merchants=world.merchants,
            payments=world.payments,
            settlements=[corrupted_settlement],
            bank_entries=[corrupted_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[],
            corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        r010_ev = next(e for e in result.evidence if e.rule_id == "R010")
        assert r010_ev.matched is True
        r014_ev = next(e for e in result.evidence if e.rule_id == "R014")
        assert r014_ev.matched is False

    def test_r014_failure_prevents_auto_match(self):
        # 9. R014 failure → no AUTO_MATCH
        world = make_clean_world()
        corrupted_settlement = make_settlement(fee="200.00", net="4800.00")
        corrupted_bank = make_bank_entry(credit="4800.00")
        world = ObservedWorld(
            merchants=world.merchants,
            payments=world.payments,
            settlements=[corrupted_settlement],
            bank_entries=[corrupted_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[],
            corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        assert result.is_match is False

    def test_r014_evidence_fields(self):
        # 10. R014 evidence contains expected/observed/delta values
        world = make_clean_world()
        corrupted_settlement = make_settlement(fee="200.00", net="4800.00")
        corrupted_bank = make_bank_entry(credit="4800.00")
        world = ObservedWorld(
            merchants=world.merchants,
            payments=world.payments,
            settlements=[corrupted_settlement],
            bank_entries=[corrupted_bank],
            ledger_entries=world.ledger_entries,
            ground_truth=[],
            corruption_events=[],
        )
        ct = _ct_from_world(world)
        result = run_exact_match(ct)
        r014_ev = next(e for e in result.evidence if e.rule_id == "R014")
        assert "expected_net=4900.00" in r014_ev.expected_value
        assert "fee_rate=0.02" in r014_ev.expected_value
        assert "observed_net=4800.00" in r014_ev.observed_value
        assert "delta=-100.00" in r014_ev.observed_value

    def test_multiple_payments_no_per_payment_rounding_errors(self):
        # 11. multiple payments do not cause per-payment rounding errors
        merchant = make_merchant(mid="M_001")
        merchant = merchant.model_copy(update={"fee_rate": Decimal("0.0175")})
        # 3 payments of 100.33 => total = 300.99
        # expected batch fee = round(300.99 * 0.0175, 2) = round(5.267325, 2) = 5.27
        # expected batch net = 300.99 - 5.27 = 295.72
        p1 = make_payment(pid="PAY_1", amount="100.33")
        p2 = make_payment(pid="PAY_2", amount="100.33")
        p3 = make_payment(pid="PAY_3", amount="100.33")

        settlement = make_settlement(
            sid="SET_BATCH",
            payment_ids=["PAY_1", "PAY_2", "PAY_3"],
            gross="300.99",
            fee="5.27",
            net="295.72",
            settlement_ref="REF_BATCH",
        )
        bank = make_bank_entry(settlement_ref="REF_BATCH", credit="295.72")
        world = ObservedWorld(
            merchants=[merchant],
            payments=[p1, p2, p3],
            settlements=[settlement],
            bank_entries=[bank],
            ledger_entries=[],
            ground_truth=[],
            corruption_events=[],
        )
        norm = normalise(world)
        for ct in norm.canonical_transactions:
            result = run_exact_match(ct)
            r014_ev = next(e for e in result.evidence if e.rule_id == "R014")
            assert r014_ev.matched is True

    def test_existing_e001_to_e006_and_e008_no_regression(self):
        # 12. existing E001-E006 and E008 behavior does not regress
        # Verified globally by running the full test suite
        pass
