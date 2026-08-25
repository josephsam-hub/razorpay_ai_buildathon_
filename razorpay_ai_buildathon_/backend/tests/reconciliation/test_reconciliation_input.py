"""
LedgerLens — ReconciliationBatch Verification Tests
==================================================
Verifies correct behavior, type constraints, and legacy parity of ReconciliationBatch.
"""

from __future__ import annotations

from decimal import Decimal
import pytest

from app.models.reconciliation_input import ReconciliationBatch, from_observed_world
from app.services.reconciliation import ReconciliationService
from app.core.reconciliation.normaliser import normalise
from app.data.generator.models import Payment, Settlement, BankEntry, LedgerEntry, Merchant

from tests.reconciliation.conftest import (
    make_clean_world,
    make_bank_entry,
    make_ledger_entry,
    make_payment,
    make_merchant,
    make_settlement,
)


def test_reconciliation_batch_construction_independent_of_observed_world():
    # Construct a ReconciliationBatch from scratch without ObservedWorld
    m = make_merchant(mid="M_TEST")
    p = make_payment(pid="PAY_TEST", amount="100.00", merchant_id="M_TEST")

    batch = ReconciliationBatch(
        payments=(p,),
        settlements=(),
        bank_entries=(),
        ledger_entries=(),
        merchants=(m,),
        batch_id="BATCH_MANUAL",
    )

    assert batch.batch_id == "BATCH_MANUAL"
    assert len(batch.payments) == 1
    assert batch.payments[0].payment_id == "PAY_TEST"


def test_reconcile_batch_matches_reconcile_legacy():
    # Verify legacy path and new path output identical results
    observed = make_clean_world()

    service = ReconciliationService()
    legacy_result, legacy_exceptions = service.reconcile(observed, batch_id="SEED_CAL")

    batch = from_observed_world(observed)
    batch_result, batch_exceptions = service.reconcile_batch(batch, batch_id="SEED_CAL")

    # Assert equivalence of the batch reconciliation result
    assert legacy_result.batch_id == batch_result.batch_id
    assert legacy_result.total_records == batch_result.total_records
    assert legacy_result.auto_matched == batch_result.auto_matched
    assert legacy_result.human_review == batch_result.human_review
    assert legacy_result.abstained == batch_result.abstained
    assert legacy_result.match_rate == batch_result.match_rate
    assert legacy_result.exception_rate == batch_result.exception_rate

    # Decisions match
    assert len(legacy_result.decisions) == len(batch_result.decisions)
    for d_leg, d_bat in zip(legacy_result.decisions, batch_result.decisions):
        assert d_leg.payment_id == d_bat.payment_id
        assert d_leg.decision == d_bat.decision
        assert d_leg.confidence == d_bat.confidence
        assert d_leg.exception_codes == d_bat.exception_codes

    # Exception records match
    assert len(legacy_exceptions) == len(batch_exceptions)
    for e_leg, e_bat in zip(legacy_exceptions, batch_exceptions):
        assert e_leg.payment_id == e_bat.payment_id
        assert e_leg.exception_code == e_bat.exception_code


def test_ground_truth_and_corruption_events_cannot_enter_reconciliation_batch():
    observed = make_clean_world()

    # Ensure attributes are present on ObservedWorld
    assert hasattr(observed, "ground_truth")
    assert hasattr(observed, "corruption_events")

    batch = from_observed_world(observed)

    # Ensure they do NOT exist on the ReconciliationBatch
    assert not hasattr(batch, "ground_truth")
    assert not hasattr(batch, "corruption_events")

    with pytest.raises(AttributeError):
        _ = batch.ground_truth


def test_duplicate_and_orphan_records_survive_adapter():
    merchant = make_merchant(mid="M_001")
    p1 = make_payment(pid="PAY_1", amount="100.00", merchant_id="M_001")
    s1 = make_settlement(sid="SET_1", payment_ids=["PAY_1"], gross="100.00", fee="2.00", net="98.00", settlement_ref="REF_1")

    # Competing bank entries (duplicates)
    b1 = make_bank_entry(bid="B_001", settlement_ref="REF_1", credit="98.00")
    b2 = make_bank_entry(bid="B_002", settlement_ref="REF_1", credit="98.00")

    # Orphan bank entry
    b_orphan = make_bank_entry(bid="B_ORPHAN", settlement_ref="REF_UNKNOWN", credit="50.00")

    from app.data.generator.world import ObservedWorld
    observed = ObservedWorld(
        merchants=[merchant],
        payments=[p1],
        settlements=[s1],
        bank_entries=[b1, b2, b_orphan],
        ledger_entries=[],
        ground_truth=[],
        corruption_events=[],
    )

    batch = from_observed_world(observed)

    norm = normalise(batch)
    # The normalise process correctly identifies duplicates and orphans from ReconciliationBatch
    assert len(norm.duplicate_bank_entries) == 1
    assert norm.duplicate_bank_entries[0].bank_entry_id == "B_002"
    assert len(norm.orphan_bank_entries) == 1
    assert norm.orphan_bank_entries[0].bank_entry_id == "B_ORPHAN"


def test_decimal_values_remain_decimal():
    merchant = make_merchant(mid="M_001")
    p1 = make_payment(pid="PAY_1", amount="100.00", merchant_id="M_001")

    batch = ReconciliationBatch(
        payments=(p1,),
        settlements=(),
        bank_entries=(),
        ledger_entries=(),
        merchants=(merchant,),
    )

    # Type remains Decimal
    assert isinstance(batch.payments[0].amount, Decimal)

    # Verification that floats cause TypeError
    p_float = make_payment(pid="PAY_FLOAT", amount="100.00", merchant_id="M_001")
    object.__setattr__(p_float, "amount", 100.0) # Bypass Pydantic Decimal coercion

    with pytest.raises(TypeError) as excinfo:
        ReconciliationBatch(
            payments=(p_float,),
            settlements=(),
            bank_entries=(),
            ledger_entries=(),
            merchants=(merchant,),
        )
    assert "must be Decimal" in str(excinfo.value)


def test_empty_batches_behave_deterministically():
    batch = ReconciliationBatch(
        payments=(),
        settlements=(),
        bank_entries=(),
        ledger_entries=(),
        merchants=(),
    )

    service = ReconciliationService()
    result, exceptions = service.reconcile_batch(batch)

    assert result.batch_id == "BATCH_EMPTY"
    assert result.total_records == 0
    assert result.auto_matched == 0
    assert result.human_review == 0
    assert result.abstained == 0
    assert len(exceptions) == 0
