"""
Tests — CanonicalTransaction normalisation.

Covers:
  - complete records (all four layers)
  - missing settlement, bank entry, ledger entry
  - presence flags
  - Decimal field types (no float)
  - output sorted by payment_id
  - duplicate bank-entry detection (Fix 2)
  - orphan detection (Fix 4)
  - latest_payment_date_in_settlement and settlement_cycle_days computed correctly
  - input immutability
"""

from __future__ import annotations

from decimal import Decimal

from app.core.reconciliation.normaliser import normalise, NormaliserResult
from app.data.generator.world import ObservedWorld

from tests.reconciliation.conftest import (
    make_bank_entry,
    make_clean_world,
    make_ledger_entry,
    make_merchant,
    make_payment,
    make_settlement,
)


def _ct(world: ObservedWorld):
    """Return the first canonical transaction from a world (convenience)."""
    return normalise(world).canonical_transactions[0]


class TestNormaliserComplete:
    def test_returns_normaliser_result(self, clean_world):
        result = normalise(clean_world)
        assert isinstance(result, NormaliserResult)

    def test_complete_canonical_has_all_layers(self, clean_world):
        result = normalise(clean_world)
        assert len(result.canonical_transactions) == 1
        ct = result.canonical_transactions[0]
        assert ct.is_fully_linked

    def test_payment_fields_populated(self, clean_world):
        ct = _ct(clean_world)
        assert ct.payment_id == "PAY_20260801_00001"
        assert ct.merchant_id == "M_001"
        assert isinstance(ct.payment_amount, Decimal)
        assert not isinstance(ct.payment_amount, float)
        assert ct.currency == "INR"

    def test_settlement_fields_populated(self, clean_world):
        ct = _ct(clean_world)
        assert ct.settlement_id is not None
        assert ct.settlement_ref == "REF_SET_00001"
        assert isinstance(ct.settlement_net_amount, Decimal)
        assert ct.settlement_net_amount == Decimal("4900.00")

    def test_bank_fields_populated(self, clean_world):
        ct = _ct(clean_world)
        assert ct.bank_entry_id is not None
        assert ct.bank_settlement_ref == "REF_SET_00001"
        assert isinstance(ct.bank_credit_amount, Decimal)
        assert ct.bank_credit_amount == Decimal("4900.00")

    def test_ledger_fields_populated(self, clean_world):
        ct = _ct(clean_world)
        assert ct.ledger_entry_id is not None
        assert ct.ledger_payment_id == "PAY_20260801_00001"
        assert isinstance(ct.allocated_amount, Decimal)

    def test_presence_flags_all_true(self, clean_world):
        ct = _ct(clean_world)
        assert ct.has_settlement is True
        assert ct.has_bank_entry is True
        assert ct.has_ledger_entry is True
        assert ct.is_fully_linked is True

    def test_latest_payment_date_in_settlement_populated(self, clean_world):
        """Single-payment settlement: latest date == payment_date."""
        ct = _ct(clean_world)
        assert ct.latest_payment_date_in_settlement is not None
        assert ct.latest_payment_date_in_settlement == ct.payment_date

    def test_settlement_cycle_days_populated(self, clean_world):
        """settlement_cycle_days is pulled from the merchant."""
        ct = _ct(clean_world)
        assert ct.settlement_cycle_days is not None
        assert isinstance(ct.settlement_cycle_days, int)


class TestNormaliserMissingSettlement:
    def test_missing_settlement_produces_none_settlement_fields(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=world.bank_entries,
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct(world)
        assert ct.settlement_id is None
        assert ct.settlement_ref is None
        assert ct.settlement_net_amount is None
        assert ct.has_settlement is False
        assert ct.is_fully_linked is False

    def test_missing_settlement_bank_unresolvable(self):
        """Bank can't be resolved without a settlement_ref."""
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=world.bank_entries,
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct(world)
        assert ct.bank_entry_id is None

    def test_missing_settlement_latest_date_is_none(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=[], bank_entries=world.bank_entries,
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct(world)
        assert ct.latest_payment_date_in_settlement is None


class TestNormaliserMissingBankEntry:
    def test_missing_bank_entry_produces_none_bank_fields(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=[],
            ledger_entries=world.ledger_entries,
            ground_truth=[], corruption_events=[],
        )
        ct = _ct(world)
        assert ct.settlement_id is not None
        assert ct.bank_entry_id is None
        assert ct.bank_credit_amount is None
        assert ct.has_bank_entry is False
        assert ct.is_fully_linked is False


class TestNormaliserMissingLedgerEntry:
    def test_missing_ledger_entry_produces_none_ledger_fields(self):
        world = make_clean_world()
        world = ObservedWorld(
            merchants=world.merchants, payments=world.payments,
            settlements=world.settlements, bank_entries=world.bank_entries,
            ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        ct = _ct(world)
        assert ct.ledger_entry_id is None
        assert ct.allocated_amount is None
        assert ct.has_ledger_entry is False
        assert ct.is_fully_linked is False


class TestNormaliserOrdering:
    def test_output_sorted_by_payment_id(self):
        m = make_merchant()
        p1 = make_payment("PAY_20260801_00003", amount="3000.00")
        p2 = make_payment("PAY_20260801_00001", amount="1000.00")
        p3 = make_payment("PAY_20260801_00002", amount="2000.00")
        s1 = make_settlement("SET_001", payment_ids=["PAY_20260801_00003"],
                             gross="3000.00", fee="60.00", net="2940.00",
                             settlement_ref="REF_001")
        s2 = make_settlement("SET_002", payment_ids=["PAY_20260801_00001"],
                             gross="1000.00", fee="20.00", net="980.00",
                             settlement_ref="REF_002")
        s3 = make_settlement("SET_003", payment_ids=["PAY_20260801_00002"],
                             gross="2000.00", fee="40.00", net="1960.00",
                             settlement_ref="REF_003")
        world = ObservedWorld(
            merchants=[m], payments=[p1, p2, p3],
            settlements=[s1, s2, s3], bank_entries=[],
            ledger_entries=[], ground_truth=[], corruption_events=[],
        )
        result = normalise(world)
        ids = [ct.payment_id for ct in result.canonical_transactions]
        assert ids == sorted(ids)

    def test_duplicate_settlement_ref_lowest_bank_id_wins(self):
        m = make_merchant()
        p = make_payment()
        s = make_settlement(payment_ids=["PAY_20260801_00001"],
                            gross="5000.00", fee="100.00", net="4900.00")
        b1 = make_bank_entry(bid="BNK_20260802_0002", credit="4900.00")
        b2 = make_bank_entry(bid="BNK_20260802_0001", credit="4900.00")
        world = ObservedWorld(
            merchants=[m], payments=[p], settlements=[s],
            bank_entries=[b1, b2], ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        ct = normalise(world).canonical_transactions[0]
        assert ct.bank_entry_id == "BNK_20260802_0001"


class TestNormaliserDuplicateDetection:
    def test_duplicate_bank_entry_detected(self):
        """Fix 2: duplicate bank entries must not be silently discarded."""
        m = make_merchant()
        p = make_payment()
        s = make_settlement(payment_ids=["PAY_20260801_00001"],
                            gross="5000.00", fee="100.00", net="4900.00")
        b1 = make_bank_entry(bid="BNK_20260802_0001", credit="4900.00")
        b2 = make_bank_entry(bid="BNK_20260802_0002", credit="4900.00")
        world = ObservedWorld(
            merchants=[m], payments=[p], settlements=[s],
            bank_entries=[b1, b2], ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        result = normalise(world)
        assert len(result.duplicate_bank_entries) == 1
        assert result.duplicate_bank_entries[0].bank_entry_id == "BNK_20260802_0002"

    def test_no_duplicates_in_clean_world(self, clean_world):
        result = normalise(clean_world)
        assert result.duplicate_bank_entries == []
        assert result.duplicate_ledger_entries == []

    def test_has_duplicates_property(self):
        m = make_merchant()
        p = make_payment()
        s = make_settlement(payment_ids=["PAY_20260801_00001"],
                            gross="5000.00", fee="100.00", net="4900.00")
        b1 = make_bank_entry(bid="BNK_20260802_0001")
        b2 = make_bank_entry(bid="BNK_20260802_0002")
        world = ObservedWorld(
            merchants=[m], payments=[p], settlements=[s],
            bank_entries=[b1, b2], ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        result = normalise(world)
        assert result.has_duplicates is True


class TestNormaliserOrphanDetection:
    def test_orphan_bank_entry_detected(self):
        """Fix 4: bank entry whose settlement_ref doesn't match any settlement."""
        m = make_merchant()
        p = make_payment()
        s = make_settlement(settlement_ref="REF_SET_00001",
                            payment_ids=["PAY_20260801_00001"],
                            gross="5000.00", fee="100.00", net="4900.00")
        orphan_bank = make_bank_entry(settlement_ref="REF_ORPHAN_99999")
        clean_bank = make_bank_entry(settlement_ref="REF_SET_00001")
        world = ObservedWorld(
            merchants=[m], payments=[p], settlements=[s],
            bank_entries=[clean_bank, orphan_bank], ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        result = normalise(world)
        assert len(result.orphan_bank_entries) == 1
        assert result.orphan_bank_entries[0].bank_entry_id == orphan_bank.bank_entry_id

    def test_orphan_settlement_detected(self):
        """Fix 4: settlement whose payment_ids are not in observed.payments."""
        m = make_merchant()
        p = make_payment("PAY_20260801_00001")
        real_s = make_settlement(payment_ids=["PAY_20260801_00001"],
                                 settlement_ref="REF_SET_00001",
                                 gross="5000.00", fee="100.00", net="4900.00")
        orphan_s = make_settlement("SET_ORPHAN_9999",
                                   payment_ids=["PAY_UNKNOWN_00099"],
                                   settlement_ref="REF_ORPHAN_00099",
                                   gross="1000.00", fee="20.00", net="980.00")
        world = ObservedWorld(
            merchants=[m], payments=[p],
            settlements=[real_s, orphan_s], bank_entries=[],
            ledger_entries=[], ground_truth=[], corruption_events=[],
        )
        result = normalise(world)
        assert len(result.orphan_settlements) == 1
        assert result.orphan_settlements[0].settlement_id == "SET_ORPHAN_9999"

    def test_orphan_ledger_entry_detected(self):
        """Fix 4: ledger entry whose payment_id is not in observed.payments."""
        m = make_merchant()
        p = make_payment("PAY_20260801_00001")
        s = make_settlement(payment_ids=["PAY_20260801_00001"],
                            gross="5000.00", fee="100.00", net="4900.00")
        b = make_bank_entry()
        real_ledger = make_ledger_entry(payment_id="PAY_20260801_00001")
        orphan_ledger = make_ledger_entry(
            lid="LED_20260802_0099",
            payment_id="PAY_UNKNOWN_00099",
        )
        world = ObservedWorld(
            merchants=[m], payments=[p], settlements=[s], bank_entries=[b],
            ledger_entries=[real_ledger, orphan_ledger],
            ground_truth=[], corruption_events=[],
        )
        result = normalise(world)
        assert len(result.orphan_ledger_entries) == 1
        assert result.orphan_ledger_entries[0].ledger_entry_id == "LED_20260802_0099"

    def test_no_orphans_in_clean_world(self, clean_world):
        result = normalise(clean_world)
        assert result.orphan_bank_entries == []
        assert result.orphan_settlements == []
        assert result.orphan_ledger_entries == []


class TestNormaliserImmutability:
    def test_input_not_mutated(self):
        world = make_clean_world()
        original_amount = world.payments[0].amount
        original_settlement_net = world.settlements[0].net_amount
        normalise(world)
        assert world.payments[0].amount == original_amount
        assert world.settlements[0].net_amount == original_settlement_net

    def test_empty_world_returns_empty_canonical_list(self):
        world = ObservedWorld(
            merchants=[], payments=[], settlements=[],
            bank_entries=[], ledger_entries=[],
            ground_truth=[], corruption_events=[],
        )
        result = normalise(world)
        assert result.canonical_transactions == []
        assert result.orphan_bank_entries == []
