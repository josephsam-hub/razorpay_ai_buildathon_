"""
Tests — DatasetIntegrityValidator catches known invariant violations.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.data.generator.models import (
    BankEntry,
    LedgerEntry,
    Merchant,
    Payment,
    Settlement,
)
from app.data.generator.validator import DatasetIntegrityValidator


def _merchant(mid="M_001") -> Merchant:
    return Merchant(
        merchant_id=mid,
        name="Test Corp",
        city="Mumbai",
        settlement_tier="T1",
        settlement_cycle_days=1,
        fee_rate=Decimal("0.0175"),
    )


def _payment(pid="PAY_0001", amount="1000.00") -> Payment:
    return Payment(
        payment_id=pid,
        merchant_id="M_001",
        amount=Decimal(amount),
        payment_date=date(2026, 8, 1),
        gateway_ref="RPY_GW_90001",
    )


def _settlement(sid="SET_0001", payment_ids=None, gross="1000.00",
                fee="17.50", net="982.50", ref="REF_SET_00001") -> Settlement:
    payment_ids = payment_ids or ["PAY_0001"]
    return Settlement(
        settlement_id=sid,
        merchant_id="M_001",
        payment_ids=payment_ids,
        settlement_date=date(2026, 8, 2),
        gross_amount=Decimal(gross),
        fee_amount=Decimal(fee),
        net_amount=Decimal(net),
        settlement_ref=ref,
    )


def _bank_entry(bid="BNK_0001", ref="REF_SET_00001", credit="982.50") -> BankEntry:
    return BankEntry(
        bank_entry_id=bid,
        merchant_id="M_001",
        settlement_ref=ref,
        credit_amount=Decimal(credit),
        value_date=date(2026, 8, 2),
        bank_ref="UTR_10001",
        narration="test",
    )


def _ledger_entry(lid="LED_0001", pid="PAY_0001", sid="SET_0001",
                  bid="BNK_0001", allocated="982.50") -> LedgerEntry:
    return LedgerEntry(
        ledger_entry_id=lid,
        merchant_id="M_001",
        payment_id=pid,
        settlement_id=sid,
        bank_entry_id=bid,
        allocated_amount=Decimal(allocated),
        posting_date=date(2026, 8, 2),
    )


@pytest.fixture
def validator():
    return DatasetIntegrityValidator()


@pytest.fixture
def clean_entities():
    """A minimal valid set of entities."""
    m = _merchant()
    p = _payment()
    s = _settlement()
    b = _bank_entry()
    le = _ledger_entry()
    return m, p, s, b, le


class TestValidatorPassesClean:
    def test_valid_entities_pass(self, validator, clean_entities):
        m, p, s, b, le = clean_entities
        result = validator.validate([m], [p], [s], [b], [le])
        assert result.passed, str(result)


class TestINV01DuplicatePaymentIds:
    def test_detects_duplicate_payment_ids(self, validator, clean_entities):
        m, p, s, b, le = clean_entities
        p2 = _payment(pid="PAY_0001", amount="2000.00")  # duplicate ID
        result = validator.validate([m], [p, p2], [s], [b], [le])
        assert not result.passed
        assert any("INV-01" in v for v in result.violations)


class TestINV05UnknownPaymentRef:
    def test_detects_unknown_payment_in_settlement(self, validator, clean_entities):
        m, p, s, b, le = clean_entities
        # Settlement references a payment that doesn't exist
        bad_s = _settlement(payment_ids=["PAY_GHOST"])
        result = validator.validate([m], [p], [bad_s], [b], [le])
        assert not result.passed
        assert any("INV-05" in v for v in result.violations)


class TestINV06UnknownSettlementRef:
    def test_detects_unknown_settlement_ref_in_bank(self, validator, clean_entities):
        m, p, s, b, le = clean_entities
        bad_b = _bank_entry(ref="REF_GHOST_99999")
        result = validator.validate([m], [p], [s], [bad_b], [le])
        assert not result.passed
        assert any("INV-06" in v for v in result.violations)


class TestINV07UnknownPaymentInLedger:
    def test_detects_unknown_payment_in_ledger(self, validator, clean_entities):
        m, p, s, b, le = clean_entities
        bad_le = _ledger_entry(pid="PAY_GHOST")
        result = validator.validate([m], [p], [s], [b], [bad_le])
        assert not result.passed
        assert any("INV-07" in v for v in result.violations)


class TestINV08GrossAmountMismatch:
    def test_detects_wrong_gross(self, validator):
        """Settlement gross != sum of payment amounts."""
        m = _merchant()
        p = _payment(amount="1000.00")
        # Gross says 2000 but batch only has 1000
        s = Settlement(
            settlement_id="SET_0001",
            merchant_id="M_001",
            payment_ids=["PAY_0001"],
            settlement_date=date(2026, 8, 2),
            gross_amount=Decimal("2000.00"),  # wrong!
            fee_amount=Decimal("35.00"),
            net_amount=Decimal("1965.00"),
            settlement_ref="REF_SET_00001",
        )
        b = _bank_entry(credit="1965.00")
        le = _ledger_entry(allocated="1965.00")
        result = validator.validate([m], [p], [s], [b], [le])
        assert not result.passed
        assert any("INV-08" in v for v in result.violations)


class TestINV10AllocationMismatch:
    def test_detects_wrong_allocation_sum(self, validator):
        """sum(allocated_amount) != settlement.net_amount."""
        m = _merchant()
        p1 = _payment("PAY_0001", "1000.00")
        p2 = _payment("PAY_0002", "500.00")
        s = Settlement(
            settlement_id="SET_0001",
            merchant_id="M_001",
            payment_ids=["PAY_0001", "PAY_0002"],
            settlement_date=date(2026, 8, 2),
            gross_amount=Decimal("1500.00"),
            fee_amount=Decimal("26.25"),
            net_amount=Decimal("1473.75"),
            settlement_ref="REF_SET_00001",
        )
        b = _bank_entry(credit="1473.75")
        le1 = _ledger_entry("LED_0001", "PAY_0001", allocated="900.00")  # wrong total
        le2 = _ledger_entry("LED_0002", "PAY_0002", allocated="500.00")  # 900+500=1400 != 1473.75
        result = validator.validate([m], [p1, p2], [s], [b], [le1, le2])
        assert not result.passed
        assert any("INV-10" in v for v in result.violations)


class TestValidationResultStr:
    def test_pass_str(self, validator, clean_entities):
        m, p, s, b, le = clean_entities
        result = validator.validate([m], [p], [s], [b], [le])
        assert "PASS" in str(result)

    def test_fail_str(self, validator, clean_entities):
        m, p, s, b, le = clean_entities
        bad_le = _ledger_entry(pid="PAY_GHOST")
        result = validator.validate([m], [p], [s], [b], [bad_le])
        assert "FAIL" in str(result)
        assert "INV-07" in str(result)
