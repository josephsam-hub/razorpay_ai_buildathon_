"""
LedgerLens Phase 2 — Corruption Engine
=========================================
Pure functions — one per E-code discrepancy type.

RULES (AGENTS.md):
  - Each function is a pure function (no side effects on the clean world).
  - Returns (modified_entity, CorruptionEvent) — never mutates input.
  - Financial delta values use Decimal — never float.
  - The CorruptionEvent preserves exact original and observed state as JSON strings.
  - The clean truth object passed in is always copied before modification.

APPROVED DISCREPANCY TYPES (Phase 2):
  E001 — missing_settlement:       Settlement record removed for a payment
  E002 — missing_bank_entry:       Bank entry removed for a settlement
  E003 — missing_ledger_entry:     Ledger entry removed for a payment
  E004 — amount_mismatch:          Bank entry credit_amount corrupted
  E005 — date_mismatch:            Bank entry value_date shifted (clamped >= payment_date)
  E006 — duplicate_bank_entry:     Bank entry duplicated with different bank_ref
  E007 — settlement_fee_variance:  Settlement fee/net corrupted; bank credit updated to match
  E008 — orphan_bank_entry:        Synthetic bank entry with no matching settlement

DEFERRED (not implemented in Phase 2):
  - duplicate_payment
  - reference_mismatch
  - ambiguous_candidate

SEEDING (CRIT-1):
  Each corruption function receives its own unique event_seed derived from:
    _derive_event_seed(master_corrupt_seed, corruption_event_sequence_number)
  This makes each operation independently reproducible.
"""

from __future__ import annotations

import copy
import json
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.data.generator.models import (
    BankEntry,
    CorruptionEvent,
    LedgerEntry,
    Settlement,
)

_TWO_PLACES = Decimal("0.01")

# Amount mismatch delta range: ±2% to ±10% of credit_amount
_MISMATCH_MIN_PCT = Decimal("0.02")
_MISMATCH_MAX_PCT = Decimal("0.10")

# Fee variance: ±1% to ±3% of gross_amount
_FEE_VARIANCE_MIN_PCT = Decimal("0.01")
_FEE_VARIANCE_MAX_PCT = Decimal("0.03")

# Date shift for date_mismatch: 1–5 days
_DATE_SHIFT_MIN = 1
_DATE_SHIFT_MAX = 5

# Orphan amount range: 20% to 80% of reference, varied deterministically
_ORPHAN_AMOUNT_MIN_PCT = Decimal("0.20")
_ORPHAN_AMOUNT_MAX_PCT = Decimal("0.80")


def derive_event_seed(master_corrupt_seed: int, event_sequence: int) -> int:
    """
    CRIT-1: Derive a unique, deterministic seed for each corruption event.

    Uses a mixing function so that:
      - Same master_corrupt_seed + same event_sequence → same result
      - Different master_corrupt_seed or event_sequence → different result
      - All event seeds within one dataset are unique (given unique sequences)
    """
    return (master_corrupt_seed * 2_654_435_761 + event_sequence * 40_503) % (2**31 - 1)


def _random_pct(rng: random.Random, min_pct: Decimal, max_pct: Decimal) -> Decimal:
    """Return a random Decimal percentage in [min_pct, max_pct] (2 d.p.)."""
    min_bps = int(min_pct * 10000)
    max_bps = int(max_pct * 10000)
    bps = rng.randint(min_bps, max_bps)
    return Decimal(bps) / Decimal(10000)


# ---------------------------------------------------------------------------
# E001 — missing_settlement
# ---------------------------------------------------------------------------

def corrupt_missing_settlement(
    payment_id: str,
    settlement: Settlement,
    event_seed: int,
    corruption_id: str,
) -> tuple[None, CorruptionEvent]:
    """Remove a settlement record (returns None to signal removal)."""
    event = CorruptionEvent(
        corruption_id=corruption_id,
        case_id=payment_id,
        corruption_type="missing_settlement",
        target_entity="settlement",
        target_record_id=settlement.settlement_id,
        original_value="<row_present>",
        observed_value="<row_removed>",
        delta=None,
        applied_seed=event_seed,
    )
    return None, event


# ---------------------------------------------------------------------------
# E002 — missing_bank_entry
# ---------------------------------------------------------------------------

def corrupt_missing_bank_entry(
    payment_id: str,
    bank_entry: BankEntry,
    event_seed: int,
    corruption_id: str,
) -> tuple[None, CorruptionEvent]:
    """Remove a bank entry record (returns None to signal removal)."""
    event = CorruptionEvent(
        corruption_id=corruption_id,
        case_id=payment_id,
        corruption_type="missing_bank_entry",
        target_entity="bank_entry",
        target_record_id=bank_entry.bank_entry_id,
        original_value="<row_present>",
        observed_value="<row_removed>",
        delta=None,
        applied_seed=event_seed,
    )
    return None, event


# ---------------------------------------------------------------------------
# E003 — missing_ledger_entry
# ---------------------------------------------------------------------------

def corrupt_missing_ledger_entry(
    payment_id: str,
    ledger_entry: LedgerEntry,
    event_seed: int,
    corruption_id: str,
) -> tuple[None, CorruptionEvent]:
    """Remove a ledger entry record (returns None to signal removal)."""
    event = CorruptionEvent(
        corruption_id=corruption_id,
        case_id=payment_id,
        corruption_type="missing_ledger_entry",
        target_entity="ledger_entry",
        target_record_id=ledger_entry.ledger_entry_id,
        original_value="<row_present>",
        observed_value="<row_removed>",
        delta=None,
        applied_seed=event_seed,
    )
    return None, event


# ---------------------------------------------------------------------------
# E004 — amount_mismatch
# ---------------------------------------------------------------------------

def corrupt_amount_mismatch(
    payment_id: str,
    bank_entry: BankEntry,
    event_seed: int,
    corruption_id: str,
) -> tuple[BankEntry, CorruptionEvent]:
    """Shift bank_entry.credit_amount by ±2%-10% of original."""
    rng = random.Random(event_seed)  # noqa: S311
    original_amount = bank_entry.credit_amount
    pct = _random_pct(rng, _MISMATCH_MIN_PCT, _MISMATCH_MAX_PCT)
    delta_amount = (original_amount * pct).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    direction = rng.choice([-1, 1])
    new_amount = original_amount + Decimal(direction) * delta_amount
    if new_amount <= 0:
        new_amount = original_amount - delta_amount  # always subtract if would go negative

    corrupted = copy.copy(bank_entry)
    object.__setattr__(corrupted, "credit_amount", new_amount)

    delta_str = str((new_amount - original_amount).quantize(_TWO_PLACES))

    event = CorruptionEvent(
        corruption_id=corruption_id,
        case_id=payment_id,
        corruption_type="amount_mismatch",
        target_entity="bank_entry",
        target_record_id=bank_entry.bank_entry_id,
        original_value=json.dumps({"credit_amount": str(original_amount)}),
        observed_value=json.dumps({"credit_amount": str(new_amount)}),
        delta=delta_str,
        applied_seed=event_seed,
    )
    return corrupted, event


# ---------------------------------------------------------------------------
# E005 — date_mismatch (CC-2: clamped so value_date >= payment_date)
# ---------------------------------------------------------------------------

def corrupt_date_mismatch(
    payment_id: str,
    bank_entry: BankEntry,
    event_seed: int,
    corruption_id: str,
    payment_date: date | None = None,
    settlement_date: date | None = None,
) -> tuple[BankEntry, CorruptionEvent]:
    """
    Shift bank_entry.value_date forward or backward.
    Ensures that the new date always falls outside the [0, 1] days window from settlement_date.
    CC-2: Clamp so the resulting date is never before payment_date.
    """
    rng = random.Random(event_seed)  # noqa: S311
    original_date = bank_entry.value_date
    ref_date = settlement_date if settlement_date is not None else original_date
    shift_days = rng.randint(_DATE_SHIFT_MIN, _DATE_SHIFT_MAX)
    direction = rng.choice([-1, 1])

    if direction == -1:
        new_date = ref_date - timedelta(days=shift_days)
        # CC-2: Clamp — value_date must not be before payment_date
        if payment_date is not None and new_date < payment_date:
            # Flip to forward shift: at least 2 days after settlement_date
            new_date = ref_date + timedelta(days=1 + shift_days)
    else:
        # Shift forward: at least 2 days after settlement_date
        new_date = ref_date + timedelta(days=1 + shift_days)

    corrupted = copy.copy(bank_entry)
    object.__setattr__(corrupted, "value_date", new_date)

    event = CorruptionEvent(
        corruption_id=corruption_id,
        case_id=payment_id,
        corruption_type="date_mismatch",
        target_entity="bank_entry",
        target_record_id=bank_entry.bank_entry_id,
        original_value=json.dumps({"value_date": original_date.isoformat()}),
        observed_value=json.dumps({"value_date": new_date.isoformat()}),
        delta=f"{(new_date - original_date).days:+d} days",
        applied_seed=event_seed,
    )
    return corrupted, event


# ---------------------------------------------------------------------------
# E006 — duplicate_bank_entry
# ---------------------------------------------------------------------------

def corrupt_duplicate_bank_entry(
    payment_id: str,
    bank_entry: BankEntry,
    event_seed: int,
    corruption_id: str,
) -> tuple[BankEntry, CorruptionEvent]:
    """
    Create a duplicate bank entry with a different bank_ref.
    The original entry remains; the duplicate is the additional record returned.
    """
    rng = random.Random(event_seed)  # noqa: S311
    new_bank_ref = f"UTR_DUP_{event_seed:010d}"
    duplicate = copy.copy(bank_entry)
    dup_id = f"{bank_entry.bank_entry_id}_DUP_{rng.randint(1, 9999):04d}"
    object.__setattr__(duplicate, "bank_entry_id", dup_id)
    object.__setattr__(duplicate, "bank_ref", new_bank_ref)

    event = CorruptionEvent(
        corruption_id=corruption_id,
        case_id=payment_id,
        corruption_type="duplicate_bank_entry",
        target_entity="bank_entry",
        target_record_id=dup_id,
        original_value=json.dumps({"bank_ref": bank_entry.bank_ref, "bank_entry_id": bank_entry.bank_entry_id}),
        observed_value=json.dumps({"bank_ref": new_bank_ref, "bank_entry_id": dup_id, "credit_amount": str(bank_entry.credit_amount)}),
        delta=None,
        applied_seed=event_seed,
    )
    return duplicate, event


# ---------------------------------------------------------------------------
# E007 — settlement_fee_variance (CRIT-2: also update bank credit)
# ---------------------------------------------------------------------------

def corrupt_settlement_fee_variance(
    payment_id: str,
    settlement: Settlement,
    bank_entry: BankEntry | None,
    event_seed: int,
    corruption_id: str,
) -> tuple[Settlement, BankEntry | None, CorruptionEvent]:
    """
    Corrupt settlement.fee_amount by ±1%-3% of gross_amount.
    Adjusts net_amount accordingly to maintain gross - fee == net.

    CRIT-2: Also updates the corresponding bank_entry.credit_amount
    to the new net_amount, so the observed settlement and bank remain
    consistent. The discrepancy is settlement-vs-clean, not settlement-vs-bank.
    """
    rng = random.Random(event_seed)  # noqa: S311
    original_fee = settlement.fee_amount
    original_net = settlement.net_amount

    pct = _random_pct(rng, _FEE_VARIANCE_MIN_PCT, _FEE_VARIANCE_MAX_PCT)
    fee_delta = (settlement.gross_amount * pct).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    direction = rng.choice([-1, 1])
    new_fee = original_fee + Decimal(direction) * fee_delta
    if new_fee < 0:
        new_fee = original_fee + fee_delta  # clamp: always increase if would go negative
    new_net = settlement.gross_amount - new_fee

    corrupted_settlement = copy.copy(settlement)
    object.__setattr__(corrupted_settlement, "fee_amount", new_fee)
    object.__setattr__(corrupted_settlement, "net_amount", new_net)

    # CRIT-2: Sync bank credit to new net
    corrupted_bank: BankEntry | None = None
    if bank_entry is not None:
        corrupted_bank = copy.copy(bank_entry)
        object.__setattr__(corrupted_bank, "credit_amount", new_net)

    delta_str = str((new_net - original_net).quantize(_TWO_PLACES))

    event = CorruptionEvent(
        corruption_id=corruption_id,
        case_id=payment_id,
        corruption_type="settlement_fee_variance",
        target_entity="settlement",
        target_record_id=settlement.settlement_id,
        original_value=json.dumps({
            "fee_amount": str(original_fee),
            "net_amount": str(original_net),
        }),
        observed_value=json.dumps({
            "fee_amount": str(new_fee),
            "net_amount": str(new_net),
            "bank_credit_amount": str(new_net),
        }),
        delta=delta_str,
        applied_seed=event_seed,
    )
    return corrupted_settlement, corrupted_bank, event


# ---------------------------------------------------------------------------
# E008 — orphan_bank_entry (CRIT-3 + CC-5)
# ---------------------------------------------------------------------------

def corrupt_orphan_bank_entry(
    payment_id: str,
    reference_entry: BankEntry,
    event_seed: int,
    corruption_id: str,
) -> tuple[BankEntry, CorruptionEvent]:
    """
    Inject a synthetic bank entry with no matching settlement_ref.

    CRIT-3: Uses corruption_id for unique orphan_ref (no reuse within dataset).
    CC-5: Uses seeded random amount in [20%, 80%] of reference — not fixed 50%.
    """
    rng = random.Random(event_seed)  # noqa: S311

    orphan_date = reference_entry.value_date + timedelta(days=rng.randint(0, 3))

    # CRIT-3: Use corruption_id directly for guaranteed uniqueness
    orphan_ref = f"REF_ORPHAN_{corruption_id}"
    orphan_bank_ref = f"UTR_ORP_{corruption_id}"

    # CC-5: Deterministic seeded amount in [20%, 80%] of reference
    pct = _random_pct(rng, _ORPHAN_AMOUNT_MIN_PCT, _ORPHAN_AMOUNT_MAX_PCT)
    orphan_amount = (reference_entry.credit_amount * pct).quantize(
        _TWO_PLACES, rounding=ROUND_HALF_UP
    )
    # Ensure positive
    if orphan_amount <= 0:
        orphan_amount = Decimal("1.00")

    orphan = BankEntry(
        bank_entry_id=f"BNK_ORP_{corruption_id}_{rng.randint(1, 99):02d}",
        merchant_id=reference_entry.merchant_id,
        settlement_ref=orphan_ref,
        credit_amount=orphan_amount,
        value_date=orphan_date,
        bank_ref=orphan_bank_ref,
        narration="[ORPHAN] synthetic unmatched credit",
    )

    event = CorruptionEvent(
        corruption_id=corruption_id,
        case_id=payment_id,
        corruption_type="orphan_bank_entry",
        target_entity="bank_entry",
        target_record_id=orphan.bank_entry_id,
        original_value="<no_clean_record>",
        observed_value=json.dumps({
            "bank_entry_id": orphan.bank_entry_id,
            "settlement_ref": orphan_ref,
            "credit_amount": str(orphan_amount),
        }),
        delta=None,
        applied_seed=event_seed,
    )
    return orphan, event
