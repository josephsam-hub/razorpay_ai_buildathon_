"""
Tests — CorruptionEngine: each E-code produces correct observed data,
correct CorruptionEvent, and correct GroundTruth alignment.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal

import pytest

from app.data.generator.config import DatasetConfig
from app.data.generator.models import BankEntry, LedgerEntry, Payment, Settlement
from app.data.generator.corruption import (
    corrupt_amount_mismatch,
    corrupt_date_mismatch,
    corrupt_duplicate_bank_entry,
    corrupt_missing_bank_entry,
    corrupt_missing_ledger_entry,
    corrupt_missing_settlement,
    corrupt_orphan_bank_entry,
    corrupt_settlement_fee_variance,
)
from app.data.generator.world import WorldBuilder, generate

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _payment(pid="PAY_0001", amount="5000.00") -> Payment:
    return Payment(
        payment_id=pid,
        merchant_id="M_001",
        amount=Decimal(amount),
        payment_date=date(2026, 8, 1),
        gateway_ref="RPY_GW_90001",
    )


def _settlement(net="4900.00", gross="5000.00", fee="100.00") -> Settlement:
    return Settlement(
        settlement_id="SET_20260802_0001",
        merchant_id="M_001",
        payment_ids=["PAY_0001"],
        settlement_date=date(2026, 8, 2),
        gross_amount=Decimal(gross),
        fee_amount=Decimal(fee),
        net_amount=Decimal(net),
        settlement_ref="REF_SET_00001",
    )


def _bank_entry(credit="4900.00") -> BankEntry:
    return BankEntry(
        bank_entry_id="BNK_20260802_0001",
        merchant_id="M_001",
        settlement_ref="REF_SET_00001",
        credit_amount=Decimal(credit),
        value_date=date(2026, 8, 2),
        bank_ref="UTR_10001",
        narration="Test Corp settlement credit",
    )


def _ledger_entry() -> LedgerEntry:
    return LedgerEntry(
        ledger_entry_id="LED_20260802_0001",
        merchant_id="M_001",
        payment_id="PAY_0001",
        settlement_id="SET_20260802_0001",
        bank_entry_id="BNK_20260802_0001",
        allocated_amount=Decimal("4900.00"),
        posting_date=date(2026, 8, 2),
    )


# ---------------------------------------------------------------------------
# E001 — missing_settlement
# ---------------------------------------------------------------------------

class TestE001MissingSettlement:
    def test_returns_none_and_event(self):
        s = _settlement()
        result, event = corrupt_missing_settlement("PAY_0001", s, 42, "CE_0001")
        assert result is None
        assert event.corruption_type == "missing_settlement"

    def test_event_preserves_original_state(self):
        s = _settlement()
        _, event = corrupt_missing_settlement("PAY_0001", s, 42, "CE_0001")
        assert event.original_value == "<row_present>"
        assert event.observed_value == "<row_removed>"
        assert event.target_record_id == s.settlement_id

    def test_does_not_mutate_settlement(self):
        s = _settlement()
        s_copy = copy.deepcopy(s)
        corrupt_missing_settlement("PAY_0001", s, 42, "CE_0001")
        assert s == s_copy


# ---------------------------------------------------------------------------
# E002 — missing_bank_entry
# ---------------------------------------------------------------------------

class TestE002MissingBankEntry:
    def test_returns_none_and_event(self):
        b = _bank_entry()
        result, event = corrupt_missing_bank_entry("PAY_0001", b, 42, "CE_0001")
        assert result is None
        assert event.corruption_type == "missing_bank_entry"
        assert event.target_entity == "bank_entry"

    def test_does_not_mutate_bank_entry(self):
        b = _bank_entry()
        b_copy = copy.deepcopy(b)
        corrupt_missing_bank_entry("PAY_0001", b, 42, "CE_0001")
        assert b == b_copy


# ---------------------------------------------------------------------------
# E003 — missing_ledger_entry
# ---------------------------------------------------------------------------

class TestE003MissingLedgerEntry:
    def test_returns_none_and_event(self):
        le = _ledger_entry()
        result, event = corrupt_missing_ledger_entry("PAY_0001", le, 42, "CE_0001")
        assert result is None
        assert event.corruption_type == "missing_ledger_entry"

    def test_event_references_correct_record(self):
        le = _ledger_entry()
        _, event = corrupt_missing_ledger_entry("PAY_0001", le, 42, "CE_0001")
        assert event.target_record_id == le.ledger_entry_id


# ---------------------------------------------------------------------------
# E004 — amount_mismatch
# ---------------------------------------------------------------------------

class TestE004AmountMismatch:
    def test_amount_is_changed(self):
        b = _bank_entry(credit="4900.00")
        b_original_amount = b.credit_amount
        corrupted, event = corrupt_amount_mismatch("PAY_0001", b, 42, "CE_0001")
        assert corrupted.credit_amount != b_original_amount

    def test_corrupted_amount_is_decimal(self):
        b = _bank_entry(credit="4900.00")
        corrupted, _ = corrupt_amount_mismatch("PAY_0001", b, 42, "CE_0001")
        assert isinstance(corrupted.credit_amount, Decimal)
        assert not isinstance(corrupted.credit_amount, float)

    def test_event_has_delta(self):
        b = _bank_entry(credit="4900.00")
        _, event = corrupt_amount_mismatch("PAY_0001", b, 42, "CE_0001")
        assert event.delta is not None
        # Delta should be parseable as Decimal
        Decimal(event.delta)

    def test_event_preserves_original_and_observed(self):
        b = _bank_entry(credit="4900.00")
        corrupted, event = corrupt_amount_mismatch("PAY_0001", b, 42, "CE_0001")
        orig = json.loads(event.original_value)
        obs = json.loads(event.observed_value)
        assert orig["credit_amount"] == "4900.00"
        assert obs["credit_amount"] == str(corrupted.credit_amount)

    def test_does_not_mutate_original(self):
        b = _bank_entry(credit="4900.00")
        b_copy = copy.deepcopy(b)
        corrupt_amount_mismatch("PAY_0001", b, 42, "CE_0001")
        assert b == b_copy


# ---------------------------------------------------------------------------
# E005 — date_mismatch
# ---------------------------------------------------------------------------

class TestE005DateMismatch:
    def test_date_is_changed(self):
        b = _bank_entry()
        original_date = b.value_date
        # payment_date=2026-08-01 is before value_date=2026-08-02, so clamping may apply
        corrupted, event = corrupt_date_mismatch(
            "PAY_0001", b, 42, "CE_0001", payment_date=date(2026, 8, 1)
        )
        assert corrupted.value_date != original_date

    def test_event_has_date_delta(self):
        b = _bank_entry()
        _, event = corrupt_date_mismatch(
            "PAY_0001", b, 42, "CE_0001", payment_date=date(2026, 8, 1)
        )
        assert event.delta is not None
        assert "days" in event.delta

    def test_does_not_mutate_original(self):
        b = _bank_entry()
        b_copy = copy.deepcopy(b)
        corrupt_date_mismatch("PAY_0001", b, 42, "CE_0001", payment_date=date(2026, 8, 1))
        assert b == b_copy

    def test_date_clamped_not_before_payment_date(self):
        """When backward shift would go before payment_date, result must be >= payment_date."""
        b = _bank_entry()  # value_date = 2026-08-02
        payment_date = date(2026, 8, 2)  # same as value_date — backward shift always clamped
        corrupted, _ = corrupt_date_mismatch(
            "PAY_0001", b, 42, "CE_0001", payment_date=payment_date
        )
        assert corrupted.value_date >= payment_date


# ---------------------------------------------------------------------------
# E006 — duplicate_bank_entry
# ---------------------------------------------------------------------------

class TestE006DuplicateBankEntry:
    def test_duplicate_has_different_bank_ref(self):
        b = _bank_entry()
        duplicate, event = corrupt_duplicate_bank_entry("PAY_0001", b, 42, "CE_0001")
        assert duplicate.bank_ref != b.bank_ref

    def test_duplicate_has_same_credit_amount(self):
        b = _bank_entry(credit="4900.00")
        duplicate, _ = corrupt_duplicate_bank_entry("PAY_0001", b, 42, "CE_0001")
        assert duplicate.credit_amount == b.credit_amount

    def test_duplicate_id_differs(self):
        b = _bank_entry()
        duplicate, _ = corrupt_duplicate_bank_entry("PAY_0001", b, 42, "CE_0001")
        assert duplicate.bank_entry_id != b.bank_entry_id

    def test_does_not_mutate_original(self):
        b = _bank_entry()
        b_copy = copy.deepcopy(b)
        corrupt_duplicate_bank_entry("PAY_0001", b, 42, "CE_0001")
        assert b == b_copy


# ---------------------------------------------------------------------------
# E007 — settlement_fee_variance
# ---------------------------------------------------------------------------

class TestE007SettlementFeeVariance:
    def test_fee_is_changed(self):
        s = _settlement()
        b = _bank_entry()
        original_fee = s.fee_amount
        corrupted_s, corrupted_b, event = corrupt_settlement_fee_variance(
            "PAY_0001", s, b, 42, "CE_0001"
        )
        assert corrupted_s.fee_amount != original_fee

    def test_gross_minus_fee_equals_net(self):
        s = _settlement()
        corrupted_s, _, _ = corrupt_settlement_fee_variance("PAY_0001", s, None, 42, "CE_0001")
        assert corrupted_s.gross_amount - corrupted_s.fee_amount == corrupted_s.net_amount

    def test_all_amounts_decimal(self):
        s = _settlement()
        corrupted_s, _, _ = corrupt_settlement_fee_variance("PAY_0001", s, None, 42, "CE_0001")
        assert isinstance(corrupted_s.fee_amount, Decimal)
        assert isinstance(corrupted_s.net_amount, Decimal)

    def test_bank_entry_credit_updated_to_new_net(self):
        """When bank_entry is provided, its credit_amount must equal the new net_amount."""
        s = _settlement()
        b = _bank_entry()
        corrupted_s, corrupted_b, event = corrupt_settlement_fee_variance(
            "PAY_0001", s, b, 42, "CE_0001"
        )
        assert corrupted_b is not None
        assert corrupted_b.credit_amount == corrupted_s.net_amount
        assert isinstance(corrupted_b.credit_amount, Decimal)

    def test_bank_entry_none_when_not_provided(self):
        s = _settlement()
        _, corrupted_b, _ = corrupt_settlement_fee_variance("PAY_0001", s, None, 42, "CE_0001")
        assert corrupted_b is None

    def test_event_corruption_type_and_entity(self):
        s = _settlement()
        _, _, event = corrupt_settlement_fee_variance("PAY_0001", s, None, 42, "CE_0001")
        assert event.corruption_type == "settlement_fee_variance"
        assert event.target_entity == "settlement"
        assert event.target_record_id == s.settlement_id

    def test_does_not_mutate_original(self):
        s = _settlement()
        b = _bank_entry()
        s_copy = copy.deepcopy(s)
        b_copy = copy.deepcopy(b)
        corrupt_settlement_fee_variance("PAY_0001", s, b, 42, "CE_0001")
        assert s == s_copy
        assert b == b_copy


# ---------------------------------------------------------------------------
# E008 — orphan_bank_entry
# ---------------------------------------------------------------------------

class TestE008OrphanBankEntry:
    def test_orphan_has_unmatched_settlement_ref(self):
        b = _bank_entry()
        orphan, event = corrupt_orphan_bank_entry("PAY_0001", b, 42, "CE_0001")
        assert "ORPHAN" in orphan.settlement_ref

    def test_event_original_value_is_no_clean_record(self):
        b = _bank_entry()
        _, event = corrupt_orphan_bank_entry("PAY_0001", b, 42, "CE_0001")
        assert event.original_value == "<no_clean_record>"

    def test_orphan_ref_unique_per_corruption_id(self):
        """CRIT-3: different corruption_ids must produce different settlement_refs."""
        b = _bank_entry()
        orphan_a, _ = corrupt_orphan_bank_entry("PAY_0001", b, 42, "CE_0001")
        orphan_b, _ = corrupt_orphan_bank_entry("PAY_0001", b, 42, "CE_0002")
        assert orphan_a.settlement_ref != orphan_b.settlement_ref

    def test_orphan_amount_is_decimal_in_range(self):
        """CC-5: orphan amount must be Decimal in [20%, 80%] of reference credit."""
        b = _bank_entry(credit="4900.00")
        orphan, _ = corrupt_orphan_bank_entry("PAY_0001", b, 42, "CE_0001")
        assert isinstance(orphan.credit_amount, Decimal)
        assert orphan.credit_amount >= b.credit_amount * Decimal("0.20")
        assert orphan.credit_amount <= b.credit_amount * Decimal("0.80")


# ---------------------------------------------------------------------------
# World-level corruption: ground truth alignment
# ---------------------------------------------------------------------------

class TestCorruptionGroundTruthAlignment:
    def test_corruption_events_link_to_ground_truth(self):
        """Every CorruptionEvent.corruption_id should appear in GroundTruth.corruption_id."""
        config = DatasetConfig.model_validate({
            "version": "test",
            "n_payments": 30,
            "n_merchants": 3,
            "seed": 55,
            "currency": "INR",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "corruption": {
                "missing_settlement": 0.1,
                "missing_bank_entry": 0.1,
                "amount_mismatch": 0.1,
                "date_mismatch": 0.05,
                "duplicate_bank_entry": 0.0,
                "settlement_fee_variance": 0.05,
                "orphan_bank_entry": 0.0,
                "missing_ledger_entry": 0.0,
            },
        })
        _, observed = generate(config)

        gt_corruption_ids = {
            gt.corruption_id
            for gt in observed.ground_truth
            if gt.corruption_id is not None
        }
        for ce in observed.corruption_events:
            assert ce.corruption_id in gt_corruption_ids, (
                f"CorruptionEvent {ce.corruption_id} not referenced in any GroundTruth"
            )

    def test_clean_truth_unchanged_after_corruption(self):
        """The clean world must be identical before and after corruption is applied."""
        config = DatasetConfig.model_validate({
            "version": "test",
            "n_payments": 20,
            "n_merchants": 3,
            "seed": 77,
            "currency": "INR",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "corruption": {
                "missing_settlement": 0.1,
                "missing_bank_entry": 0.1,
                "amount_mismatch": 0.1,
                "date_mismatch": 0.05,
                "duplicate_bank_entry": 0.0,
                "settlement_fee_variance": 0.05,
                "orphan_bank_entry": 0.0,
                "missing_ledger_entry": 0.0,
            },
        })
        builder = WorldBuilder(config)
        clean = builder.build_clean()

        # Record clean state
        clean_payment_amounts = [p.amount for p in clean.payments]
        clean_settlement_nets = [s.net_amount for s in clean.settlements]
        clean_bank_credits = [b.credit_amount for b in clean.bank_entries]
        clean_ledger_amounts = [le.allocated_amount for le in clean.ledger_entries]

        # Apply corruption
        _ = builder.corrupt(clean)

        # Clean world must be unchanged
        assert [p.amount for p in clean.payments] == clean_payment_amounts
        assert [s.net_amount for s in clean.settlements] == clean_settlement_nets
        assert [b.credit_amount for b in clean.bank_entries] == clean_bank_credits
        assert [le.allocated_amount for le in clean.ledger_entries] == clean_ledger_amounts

    def test_each_bank_entry_corrupted_at_most_once(self):
        """HIGH-1: No bank entry may appear as the target of more than one CorruptionEvent.

        Multiple payments in the same settlement batch share one bank entry.
        Corrupting it twice would make the second event's original_value reflect
        an already-corrupted state, invalidating ground truth.
        """
        # Use high bank-targeting corruption rates to maximise chance of collision
        config = DatasetConfig.model_validate({
            "version": "test",
            "n_payments": 50,
            "n_merchants": 3,
            "seed": 42,
            "currency": "INR",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "corruption": {
                "missing_settlement": 0.0,
                "missing_bank_entry": 0.2,
                "amount_mismatch": 0.2,
                "date_mismatch": 0.2,
                "duplicate_bank_entry": 0.1,
                "settlement_fee_variance": 0.0,
                "orphan_bank_entry": 0.0,
                "missing_ledger_entry": 0.0,
            },
        })
        _, observed = generate(config)

        bank_targeting_types = {
            "missing_bank_entry",
            "amount_mismatch",
            "date_mismatch",
            "duplicate_bank_entry",
        }
        targeted_bank_ids: list[str] = [
            ce.target_record_id
            for ce in observed.corruption_events
            if ce.corruption_type in bank_targeting_types
        ]
        # Each bank entry ID must appear at most once across all bank-targeting events
        assert len(targeted_bank_ids) == len(set(targeted_bank_ids)), (
            "A bank entry was targeted by more than one corruption event"
        )
