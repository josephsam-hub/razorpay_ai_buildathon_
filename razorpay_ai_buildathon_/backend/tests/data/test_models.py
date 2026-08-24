"""
Tests — Pydantic model schema and Decimal precision.
Verifies that all financial fields are Decimal and Faker-sourced
fields are strings only.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime, timezone

import pytest

from app.data.generator.models import (
    BankEntry,
    CorruptionEvent,
    DatasetMetadata,
    GroundTruth,
    LedgerEntry,
    Merchant,
    Payment,
    Settlement,
)


# ---------------------------------------------------------------------------
# Merchant
# ---------------------------------------------------------------------------

class TestMerchant:
    def test_fee_rate_is_decimal(self):
        m = Merchant(
            merchant_id="M_001",
            name="Test Corp",
            city="Mumbai",
            settlement_tier="T1",
            settlement_cycle_days=1,
            fee_rate=Decimal("0.0175"),
        )
        assert isinstance(m.fee_rate, Decimal)
        assert not isinstance(m.fee_rate, float)

    def test_name_and_city_are_strings(self):
        m = Merchant(
            merchant_id="M_001",
            name="Test Corp",
            city="Delhi",
            settlement_tier="T2",
            settlement_cycle_days=2,
            fee_rate=Decimal("0.02"),
        )
        # Faker-generated fields must be str — never Decimal or numeric
        assert isinstance(m.name, str)
        assert isinstance(m.city, str)

    def test_fee_rate_out_of_range_raises(self):
        with pytest.raises(ValueError):
            Merchant(
                merchant_id="M_001",
                name="X",
                city="Y",
                settlement_tier="T1",
                settlement_cycle_days=1,
                fee_rate=Decimal("0.5"),  # 50% — out of range
            )


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

class TestPayment:
    def test_amount_is_decimal(self):
        p = Payment(
            payment_id="PAY_20260801_0001",
            merchant_id="M_001",
            amount=Decimal("1500.00"),
            payment_date=date(2026, 8, 1),
            gateway_ref="RPY_GW_90001",
        )
        assert isinstance(p.amount, Decimal)
        assert not isinstance(p.amount, float)

    def test_negative_amount_raises(self):
        with pytest.raises(ValueError):
            Payment(
                payment_id="PAY_20260801_0001",
                merchant_id="M_001",
                amount=Decimal("-100.00"),
                payment_date=date(2026, 8, 1),
                gateway_ref="RPY_GW_90001",
            )

    def test_zero_amount_raises(self):
        with pytest.raises(ValueError):
            Payment(
                payment_id="PAY_20260801_0001",
                merchant_id="M_001",
                amount=Decimal("0"),
                payment_date=date(2026, 8, 1),
                gateway_ref="RPY_GW_90001",
            )


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

class TestSettlement:
    def test_net_amount_validation(self):
        s = Settlement(
            settlement_id="SET_20260802_0001",
            merchant_id="M_001",
            payment_ids=["PAY_0001", "PAY_0002"],
            settlement_date=date(2026, 8, 2),
            gross_amount=Decimal("3700.00"),
            fee_amount=Decimal("64.75"),
            net_amount=Decimal("3635.25"),
            settlement_ref="REF_SET_00001",
        )
        assert s.net_amount == Decimal("3635.25")

    def test_wrong_net_raises(self):
        with pytest.raises(ValueError, match="net_amount"):
            Settlement(
                settlement_id="SET_20260802_0001",
                merchant_id="M_001",
                payment_ids=["PAY_0001"],
                settlement_date=date(2026, 8, 2),
                gross_amount=Decimal("1000.00"),
                fee_amount=Decimal("20.00"),
                net_amount=Decimal("990.00"),  # wrong — should be 980.00
                settlement_ref="REF_SET_00001",
            )

    def test_all_amounts_decimal(self):
        s = Settlement(
            settlement_id="SET_20260802_0001",
            merchant_id="M_001",
            payment_ids=["PAY_0001"],
            settlement_date=date(2026, 8, 2),
            gross_amount=Decimal("1000.00"),
            fee_amount=Decimal("20.00"),
            net_amount=Decimal("980.00"),
            settlement_ref="REF_SET_00001",
        )
        assert isinstance(s.gross_amount, Decimal)
        assert isinstance(s.fee_amount, Decimal)
        assert isinstance(s.net_amount, Decimal)


# ---------------------------------------------------------------------------
# BankEntry
# ---------------------------------------------------------------------------

class TestBankEntry:
    def test_narration_is_string(self):
        b = BankEntry(
            bank_entry_id="BNK_20260802_0001",
            merchant_id="M_001",
            settlement_ref="REF_SET_00001",
            credit_amount=Decimal("980.00"),
            value_date=date(2026, 8, 2),
            bank_ref="UTR_10001",
            narration="Test Corp settlement credit",
        )
        # narration must be str (Faker-sourced) — never Decimal
        assert isinstance(b.narration, str)
        assert isinstance(b.credit_amount, Decimal)

    def test_credit_amount_positive(self):
        with pytest.raises(ValueError):
            BankEntry(
                bank_entry_id="BNK_20260802_0001",
                merchant_id="M_001",
                settlement_ref="REF_SET_00001",
                credit_amount=Decimal("0"),
                value_date=date(2026, 8, 2),
                bank_ref="UTR_10001",
                narration="test",
            )


# ---------------------------------------------------------------------------
# LedgerEntry
# ---------------------------------------------------------------------------

class TestLedgerEntry:
    def test_allocated_amount_is_decimal(self):
        le = LedgerEntry(
            ledger_entry_id="LED_20260802_0001",
            merchant_id="M_001",
            payment_id="PAY_0001",
            settlement_id="SET_20260802_0001",
            bank_entry_id="BNK_20260802_0001",
            allocated_amount=Decimal("2455.58"),
            posting_date=date(2026, 8, 2),
        )
        assert isinstance(le.allocated_amount, Decimal)
        assert not isinstance(le.allocated_amount, float)


# ---------------------------------------------------------------------------
# CorruptionEvent
# ---------------------------------------------------------------------------

class TestCorruptionEvent:
    def test_construction(self):
        ce = CorruptionEvent(
            corruption_id="CE_20260801_0001",
            case_id="PAY_0001",
            corruption_type="amount_mismatch",
            target_entity="bank_entry",
            target_record_id="BNK_0001",
            original_value='{"credit_amount": "4900.00"}',
            observed_value='{"credit_amount": "4850.00"}',
            delta="-50.00",
            applied_seed=46,
        )
        assert ce.delta == "-50.00"
        assert ce.corruption_type == "amount_mismatch"

    def test_delta_can_be_none(self):
        ce = CorruptionEvent(
            corruption_id="CE_20260801_0001",
            case_id="PAY_0001",
            corruption_type="missing_bank_entry",
            target_entity="bank_entry",
            target_record_id="BNK_0001",
            original_value="<row_present>",
            observed_value="<row_removed>",
            applied_seed=46,
        )
        assert ce.delta is None


# ---------------------------------------------------------------------------
# GroundTruth
# ---------------------------------------------------------------------------

class TestGroundTruth:
    def test_clean_case(self):
        gt = GroundTruth(
            ground_truth_id="GT_20260801_0001",
            payment_id="PAY_0001",
            expected_decision="AUTO_MATCH",
        )
        assert gt.corruption_id is None
        assert gt.discrepancy_type is None
        assert gt.clean_settlement_net_amount is None
        assert gt.clean_allocated_amount is None

    def test_corrupted_case(self):
        gt = GroundTruth(
            ground_truth_id="GT_20260801_0002",
            payment_id="PAY_0002",
            expected_decision="HUMAN_REVIEW",
            discrepancy_type="amount_mismatch",
            discrepancy_code="E004",
            corruption_id="CE_20260801_0001",
            injected_layer="bank",
            clean_settlement_net_amount=Decimal("4900.00"),
            clean_allocated_amount=Decimal("4900.00"),
        )
        assert isinstance(gt.clean_settlement_net_amount, Decimal)
        assert isinstance(gt.clean_allocated_amount, Decimal)
        assert gt.corruption_id == "CE_20260801_0001"


# ---------------------------------------------------------------------------
# DatasetMetadata
# ---------------------------------------------------------------------------

class TestDatasetMetadata:
    def test_construction(self):
        meta = DatasetMetadata(
            dataset_version="1.0",
            generator_version="0.1.0",
            seed=42,
            currency="INR",
            generation_timestamp=datetime.now(tz=timezone.utc),
            record_counts={"payments": 100, "settlements": 52},
            corruption_profile={"clean": 70, "amount_mismatch": 5},
            config_hash="sha256:abc123",
            file_hashes={"payments.csv": "sha256:def456"},
        )
        assert meta.seed == 42
        assert meta.currency == "INR"
        assert meta.record_counts["payments"] == 100
