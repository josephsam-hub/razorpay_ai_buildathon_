"""
Tests — Per-payment ledger allocation invariant.
Critical test: sum(allocated_amount for batch) == settlement.net_amount exactly.
Covers all batch sizes 1–5.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import pytest

from app.data.generator.config import DatasetConfig
from app.data.generator.merchants import make_merchants
from app.data.generator.payments import make_payments
from app.data.generator.settlements import make_settlements
from app.data.generator.bank import make_bank_entries
from app.data.generator.ledger import make_ledger_entries, _allocate
from app.data.generator.models import Payment, Settlement


# ---------------------------------------------------------------------------
# Direct allocation function tests
# ---------------------------------------------------------------------------

def _make_payment(pid: str, amount: Decimal) -> Payment:
    from datetime import date
    return Payment(
        payment_id=pid,
        merchant_id="M_001",
        amount=amount,
        payment_date=date(2026, 8, 1),
        gateway_ref=f"RPY_GW_{pid}",
    )


def _make_settlement(gross: Decimal, fee_rate: Decimal, payment_ids: list[str]) -> Settlement:
    from datetime import date
    fee = (gross * fee_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    net = gross - fee
    return Settlement(
        settlement_id="SET_TEST_0001",
        merchant_id="M_001",
        payment_ids=payment_ids,
        settlement_date=date(2026, 8, 2),
        gross_amount=gross,
        fee_amount=fee,
        net_amount=net,
        settlement_ref="REF_SET_TEST",
    )


@pytest.mark.parametrize("batch_size", [1, 2, 3, 4, 5])
def test_allocation_sums_to_net_all_batch_sizes(batch_size):
    """CRITICAL: sum(allocated_amount) == settlement.net_amount for all batch sizes."""
    fee_rate = Decimal("0.0175")
    # Use amounts that would cause rounding edge cases
    amounts = [
        Decimal("2500.00"),
        Decimal("1200.00"),
        Decimal("3333.33"),
        Decimal("777.77"),
        Decimal("12345.67"),
    ]
    batch_amounts = amounts[:batch_size]
    gross = sum(batch_amounts)
    payments = [_make_payment(f"PAY_{i:04d}", amt) for i, amt in enumerate(batch_amounts)]
    settlement = _make_settlement(gross, fee_rate, [p.payment_id for p in payments])

    allocations = _allocate(payments, settlement)

    assert len(allocations) == batch_size
    total = sum(allocations)
    assert total == settlement.net_amount, (
        f"batch_size={batch_size}: sum(allocated)={total} != net={settlement.net_amount}\n"
        f"allocations={allocations}"
    )


def test_allocation_single_payment():
    """Single payment: allocated_amount == net_amount."""
    payment = _make_payment("PAY_0001", Decimal("5000.00"))
    settlement = _make_settlement(Decimal("5000.00"), Decimal("0.02"), ["PAY_0001"])
    allocations = _allocate([payment], settlement)
    assert allocations == [settlement.net_amount]


def test_allocation_equal_payments():
    """Equal-amount payments should allocate equal or near-equal shares."""
    payments = [_make_payment(f"PAY_{i}", Decimal("1000.00")) for i in range(3)]
    gross = Decimal("3000.00")
    settlement = _make_settlement(gross, Decimal("0.02"), [p.payment_id for p in payments])

    allocations = _allocate(payments, settlement)
    total = sum(allocations)
    assert total == settlement.net_amount

    # Each should be approximately equal (within 0.01)
    for a in allocations:
        assert abs(a - allocations[0]) <= Decimal("0.01")


def test_allocation_no_float_in_result():
    """Allocated amounts must be Decimal instances, not float."""
    payments = [_make_payment("PAY_0001", Decimal("1500.00")),
                _make_payment("PAY_0002", Decimal("500.00"))]
    settlement = _make_settlement(Decimal("2000.00"), Decimal("0.0175"), [p.payment_id for p in payments])
    allocations = _allocate(payments, settlement)
    for a in allocations:
        assert isinstance(a, Decimal), f"Expected Decimal, got {type(a)}"
        assert not isinstance(a, float)


def test_allocation_last_payment_gets_remainder():
    """Verify last-payment-gets-remainder strategy prevents rounding error accumulation."""
    # Choose amounts known to create rounding edge cases
    amounts = [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    payments = [_make_payment(f"PAY_{i}", amt) for i, amt in enumerate(amounts)]
    gross = sum(amounts)
    settlement = _make_settlement(gross, Decimal("0.02"), [p.payment_id for p in payments])
    allocations = _allocate(payments, settlement)
    assert sum(allocations) == settlement.net_amount


# ---------------------------------------------------------------------------
# Integration test: full pipeline allocation invariant
# ---------------------------------------------------------------------------

def test_full_pipeline_allocation_invariant():
    """End-to-end: generate with variable batching, verify all settlement INV-10."""
    config = DatasetConfig.model_validate({
        "version": "test",
        "n_payments": 30,
        "n_merchants": 3,
        "seed": 123,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-15",
        "min_batch_size": 1,
        "max_batch_size": 5,
        "corruption": {
            "missing_settlement": 0.0,
            "missing_bank_entry": 0.0,
            "missing_ledger_entry": 0.0,
            "amount_mismatch": 0.0,
            "date_mismatch": 0.0,
            "duplicate_bank_entry": 0.0,
            "settlement_fee_variance": 0.0,
            "orphan_bank_entry": 0.0,
        },
    })
    merchants = make_merchants(config, 1)
    payments = make_payments(config, merchants, 2)
    settlements = make_settlements(config, payments, merchants, 3)
    bank_entries = make_bank_entries(config, settlements, merchants, 4)
    ledger_entries = make_ledger_entries(config, payments, settlements, bank_entries, 5)

    # Group ledger entries by settlement_id
    settlement_to_ledgers: dict[str, list] = {}
    for le in ledger_entries:
        settlement_to_ledgers.setdefault(le.settlement_id, []).append(le)

    violations = []
    for s in settlements:
        batch_ledgers = settlement_to_ledgers.get(s.settlement_id, [])
        if not batch_ledgers:
            continue
        total = sum(le.allocated_amount for le in batch_ledgers)
        if total != s.net_amount:
            violations.append(
                f"Settlement {s.settlement_id} (batch_size={len(s.payment_ids)}): "
                f"sum={total} != net={s.net_amount}"
            )

    assert not violations, "\n".join(violations)


def test_variable_batch_sizes_present():
    """Verify that multiple batch sizes are actually generated."""
    config = DatasetConfig.model_validate({
        "version": "test",
        "n_payments": 50,
        "n_merchants": 3,
        "seed": 999,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "min_batch_size": 1,
        "max_batch_size": 5,
        "corruption": {
            "missing_settlement": 0.0, "missing_bank_entry": 0.0,
            "missing_ledger_entry": 0.0, "amount_mismatch": 0.0,
            "date_mismatch": 0.0, "duplicate_bank_entry": 0.0,
            "settlement_fee_variance": 0.0, "orphan_bank_entry": 0.0,
        },
    })
    merchants = make_merchants(config, 1)
    payments = make_payments(config, merchants, 2)
    settlements = make_settlements(config, payments, merchants, 3)

    batch_sizes = {len(s.payment_ids) for s in settlements}
    # With 50 payments across 3 merchants and seed=999, expect multiple batch sizes
    assert len(batch_sizes) > 1, (
        f"Expected multiple batch sizes, got only: {batch_sizes}"
    )
