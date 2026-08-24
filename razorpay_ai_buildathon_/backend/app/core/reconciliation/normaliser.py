"""
LedgerLens Phase 3 — Normaliser
================================
Converts an ObservedWorld into a NormaliserResult containing:
  - canonical_transactions : list[CanonicalTransaction] — one per payment
  - duplicate_bank_entries : list[BankEntry]            — Fix 2: never silently discarded
  - duplicate_ledger_entries: list[LedgerEntry]          — Fix 2
  - orphan_bank_entries    : list[BankEntry]             — Fix 4: no matching settlement
  - orphan_settlements     : list[Settlement]            — Fix 4: no payment references it
  - orphan_ledger_entries  : list[LedgerEntry]           — Fix 4: payment not in world

RULES:
  - ObservedWorld is never mutated.
  - Payment, Settlement, BankEntry, LedgerEntry are never mutated.
  - Missing linked records produce None fields in CanonicalTransaction.
  - Output canonical list is sorted by payment_id (lexicographic) for determinism.

DUPLICATE SEMANTICS (Fix 2):
  A duplicate bank entry is one that shares a settlement_ref with another
  bank entry. ALL duplicates are preserved in NormaliserResult.duplicate_bank_entries.
  The canonical transaction receives the bank entry with the lexicographically
  smallest bank_entry_id. This choice is deterministic and ensures the engine
  sees a consistent view, while ALL competing entries remain available for
  audit and exception routing.

ORPHAN SEMANTICS (Fix 4):
  - orphan_bank_entries: bank entries whose settlement_ref is not found in
    any known settlement (not reachable from the payment→settlement chain).
  - orphan_settlements: settlements whose payment_ids list contains no payment
    that exists in observed.payments.
  - orphan_ledger_entries: ledger entries whose payment_id is not found in
    observed.payments.

RELATIONSHIP RESOLUTION ORDER:
  1. payment_id → Settlement  (via settlement.payment_ids membership)
  2. settlement.settlement_ref → BankEntry  (via bank_entry.settlement_ref)
  3. payment_id → LedgerEntry  (via ledger_entry.payment_id — one per payment)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.data.generator.models import BankEntry, LedgerEntry, Settlement
from app.data.generator.world import ObservedWorld
from app.models.canonical import CanonicalTransaction


@dataclass
class NormaliserResult:
    """
    Full output of the normalisation pass.

    canonical_transactions is sorted by payment_id (deterministic).
    All other lists are sorted by their primary ID field (deterministic).
    """

    canonical_transactions: list[CanonicalTransaction]

    # Fix 2 — duplicate records (never silently discarded)
    duplicate_bank_entries: list[BankEntry] = field(default_factory=list)
    duplicate_ledger_entries: list[LedgerEntry] = field(default_factory=list)

    # Fix 4 — orphan records (not reachable from any payment)
    orphan_bank_entries: list[BankEntry] = field(default_factory=list)
    orphan_settlements: list[Settlement] = field(default_factory=list)
    orphan_ledger_entries: list[LedgerEntry] = field(default_factory=list)

    @property
    def has_duplicates(self) -> bool:
        return bool(self.duplicate_bank_entries or self.duplicate_ledger_entries)

    @property
    def has_orphans(self) -> bool:
        return bool(
            self.orphan_bank_entries
            or self.orphan_settlements
            or self.orphan_ledger_entries
        )


def normalise(observed: ObservedWorld) -> NormaliserResult:
    """
    Full normalisation pass over an ObservedWorld.

    Returns a NormaliserResult with canonical transactions, duplicates,
    and orphans. Never mutates any input object.
    """
    known_payment_ids: set[str] = {p.payment_id for p in observed.payments}
    known_settlement_refs: set[str] = {s.settlement_ref for s in observed.settlements}

    # -- Build lookup maps --
    payment_to_settlement = _build_payment_to_settlement(observed)
    ref_to_bank, duplicate_banks = _build_ref_to_bank_with_duplicates(observed)
    payment_to_ledger, duplicate_ledgers = _build_payment_to_ledger_with_duplicates(observed)
    merchant_map = {m.merchant_id: m for m in observed.merchants}
    payment_map = {p.payment_id: p for p in observed.payments}

    # -- Build canonical transactions --
    canonical_list: list[CanonicalTransaction] = []

    for payment in observed.payments:
        pid = payment.payment_id
        settlement = payment_to_settlement.get(pid)
        bank_entry = ref_to_bank.get(settlement.settlement_ref) if settlement else None
        ledger_entry = payment_to_ledger.get(pid)

        merchant = merchant_map.get(payment.merchant_id)
        settlement_cycle_days = merchant.settlement_cycle_days if merchant else None

        latest_payment_date_in_settlement = None
        if settlement:
            batch_payment_dates = [
                payment_map[p_id].payment_date
                for p_id in settlement.payment_ids
                if p_id in payment_map
            ]
            if batch_payment_dates:
                latest_payment_date_in_settlement = max(batch_payment_dates)

        ct = CanonicalTransaction(
            # Payment layer — always present
            payment_id=pid,
            merchant_id=payment.merchant_id,
            payment_amount=payment.amount,
            currency=payment.currency,
            payment_date=payment.payment_date,
            gateway_ref=payment.gateway_ref,

            # Settlement layer
            settlement_id=settlement.settlement_id if settlement else None,
            settlement_ref=settlement.settlement_ref if settlement else None,
            settlement_date=settlement.settlement_date if settlement else None,
            settlement_gross_amount=settlement.gross_amount if settlement else None,
            settlement_fee_amount=settlement.fee_amount if settlement else None,
            settlement_net_amount=settlement.net_amount if settlement else None,
            settlement_merchant_id=settlement.merchant_id if settlement else None,
            settlement_payment_ids=list(settlement.payment_ids) if settlement else [],
            latest_payment_date_in_settlement=latest_payment_date_in_settlement,
            settlement_cycle_days=settlement_cycle_days,

            # Bank entry layer
            bank_entry_id=bank_entry.bank_entry_id if bank_entry else None,
            bank_ref=bank_entry.bank_ref if bank_entry else None,
            bank_settlement_ref=bank_entry.settlement_ref if bank_entry else None,
            bank_credit_amount=bank_entry.credit_amount if bank_entry else None,
            value_date=bank_entry.value_date if bank_entry else None,

            # Ledger entry layer
            ledger_entry_id=ledger_entry.ledger_entry_id if ledger_entry else None,
            ledger_payment_id=ledger_entry.payment_id if ledger_entry else None,
            ledger_settlement_id=ledger_entry.settlement_id if ledger_entry else None,
            ledger_bank_entry_id=ledger_entry.bank_entry_id if ledger_entry else None,
            allocated_amount=ledger_entry.allocated_amount if ledger_entry else None,
            posting_date=ledger_entry.posting_date if ledger_entry else None,
        )
        canonical_list.append(ct)


    canonical_list.sort(key=lambda c: c.payment_id)

    # -- Fix 4: Detect orphan records --
    orphan_banks = _find_orphan_bank_entries(observed, known_settlement_refs)
    orphan_settlements = _find_orphan_settlements(observed, known_payment_ids)
    orphan_ledgers = _find_orphan_ledger_entries(observed, known_payment_ids)

    return NormaliserResult(
        canonical_transactions=canonical_list,
        duplicate_bank_entries=sorted(duplicate_banks, key=lambda b: b.bank_entry_id),
        duplicate_ledger_entries=sorted(duplicate_ledgers, key=lambda le: le.ledger_entry_id),
        orphan_bank_entries=sorted(orphan_banks, key=lambda b: b.bank_entry_id),
        orphan_settlements=sorted(orphan_settlements, key=lambda s: s.settlement_id),
        orphan_ledger_entries=sorted(orphan_ledgers, key=lambda le: le.ledger_entry_id),
    )


# ---------------------------------------------------------------------------
# Internal helpers — deterministic map builders
# ---------------------------------------------------------------------------

def _build_payment_to_settlement(observed: ObservedWorld) -> dict:
    """
    Map payment_id → Settlement.
    Settlements sorted by settlement_id; first one found for a pid wins.
    """
    sorted_settlements = sorted(observed.settlements, key=lambda s: s.settlement_id)
    mapping: dict = {}
    for s in sorted_settlements:
        for pid in s.payment_ids:
            if pid not in mapping:
                mapping[pid] = s
    return mapping


def _build_ref_to_bank_with_duplicates(
    observed: ObservedWorld,
) -> tuple[dict, list[BankEntry]]:
    """
    Map settlement_ref → primary BankEntry (smallest bank_entry_id wins).
    All non-primary entries for the same ref are returned as duplicates.

    Fix 2: duplicates are NEVER discarded — they are returned for exception routing.
    """
    sorted_banks = sorted(observed.bank_entries, key=lambda b: b.bank_entry_id)
    mapping: dict = {}
    duplicates: list[BankEntry] = []

    for b in sorted_banks:
        if b.settlement_ref not in mapping:
            mapping[b.settlement_ref] = b
        else:
            duplicates.append(b)

    return mapping, duplicates


def _build_payment_to_ledger_with_duplicates(
    observed: ObservedWorld,
) -> tuple[dict, list[LedgerEntry]]:
    """
    Map payment_id → primary LedgerEntry (smallest ledger_entry_id wins).
    All non-primary entries for the same payment_id are returned as duplicates.

    Fix 2: duplicates are NEVER discarded.
    """
    sorted_ledgers = sorted(observed.ledger_entries, key=lambda le: le.ledger_entry_id)
    mapping: dict = {}
    duplicates: list[LedgerEntry] = []

    for le in sorted_ledgers:
        if le.payment_id not in mapping:
            mapping[le.payment_id] = le
        else:
            duplicates.append(le)

    return mapping, duplicates


# ---------------------------------------------------------------------------
# Fix 4 — Orphan detectors
# ---------------------------------------------------------------------------

def _find_orphan_bank_entries(
    observed: ObservedWorld,
    known_settlement_refs: set[str],
) -> list[BankEntry]:
    """
    Bank entries whose settlement_ref is not found in any known settlement.
    These are 'orphan' bank entries — credited to an unmatched reference.
    Corresponds to Phase 2 E008 (orphan_bank_entry) corruption type.
    """
    return [
        b for b in observed.bank_entries
        if b.settlement_ref not in known_settlement_refs
    ]


def _find_orphan_settlements(
    observed: ObservedWorld,
    known_payment_ids: set[str],
) -> list[Settlement]:
    """
    Settlements where NONE of their payment_ids exist in the observed payment list.
    These are 'orphan' settlements — they reference payments not in this batch.
    """
    return [
        s for s in observed.settlements
        if not any(pid in known_payment_ids for pid in s.payment_ids)
    ]


def _find_orphan_ledger_entries(
    observed: ObservedWorld,
    known_payment_ids: set[str],
) -> list[LedgerEntry]:
    """
    Ledger entries whose payment_id is not found in observed.payments.
    These are 'orphan' ledger entries — posted against an unknown payment.
    """
    return [
        le for le in observed.ledger_entries
        if le.payment_id not in known_payment_ids
    ]
