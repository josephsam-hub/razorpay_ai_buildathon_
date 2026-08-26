"""
LedgerLens Phase 2 — World Builder
=====================================
Assembles CleanWorld and ObservedWorld from factory outputs.

ARCHITECTURE:
  CleanWorld     — all 5 entity lists in pristine state; NEVER MUTATED
  ObservedWorld  — corrupted copies + ground truth + corruption events
  WorldBuilder   — orchestrates the full generation pipeline

SEEDING STRATEGY (5 independent streams):
  master_seed                          -> derives all sub-seeds
  master_seed + 1  (merchant_seed)     -> merchant names/cities
  master_seed + 2  (payment_seed)      -> payment amounts/dates
  master_seed + 3  (settlement_seed)   -> batch sizes
  master_seed + 4  (bank_seed)         -> value_date offsets, narrations
  master_seed + 5  (ledger_seed)       -> posting_date offsets
  master_seed + 6  (corrupt_seed)      -> corruption selection and parameters
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from decimal import Decimal

from app.data.generator.bank import make_bank_entries
from app.data.generator.config import DatasetConfig
from app.data.generator.corruption import (
    corrupt_amount_mismatch,
    corrupt_date_mismatch,
    corrupt_duplicate_bank_entry,
    corrupt_missing_bank_entry,
    corrupt_missing_ledger_entry,
    corrupt_missing_settlement,
    corrupt_orphan_bank_entry,
    corrupt_settlement_fee_variance,
    derive_event_seed,
)
from app.data.generator.ledger import make_ledger_entries
from app.data.generator.merchants import make_merchants
from app.data.generator.models import (
    BankEntry,
    CorruptionEvent,
    GroundTruth,
    LedgerEntry,
    Merchant,
    Payment,
    Settlement,
)
from app.data.generator.payments import make_payments
from app.data.generator.settlements import make_settlements


@dataclass
class CleanWorld:
    """
    Complete clean synthetic world.
    INVARIANT: fields on this object must never be mutated after construction.
    """

    merchants: list[Merchant]
    payments: list[Payment]
    settlements: list[Settlement]
    bank_entries: list[BankEntry]
    ledger_entries: list[LedgerEntry]


@dataclass
class ObservedWorld:
    """
    The world as seen by the reconciliation engine — may contain corruptions.
    Includes ground truth and corruption events (hidden from engine).
    """

    merchants: list[Merchant]           # unchanged (reference data)
    payments: list[Payment]             # unchanged (payment is the anchor)
    settlements: list[Settlement]       # may have rows removed (E001) or modified (E007)
    bank_entries: list[BankEntry]       # may be removed (E002), modified (E004/E005), duplicated (E006), orphaned (E008)
    ledger_entries: list[LedgerEntry]   # may have rows removed (E003)
    ground_truth: list[GroundTruth]     # evaluator only
    corruption_events: list[CorruptionEvent]  # evaluator only


def _derive_seed(master: int, offset: int) -> int:
    """Derive a child seed from master + offset (simple, deterministic)."""
    return (master * 1_000_003 + offset) % (2**31 - 1)


class WorldBuilder:
    """
    Orchestrates clean world construction then controlled corruption.

    Usage:
        builder = WorldBuilder(config)
        clean = builder.build_clean()
        observed = builder.corrupt(clean)
    """

    def __init__(self, config: DatasetConfig) -> None:
        self.config = config
        self._merchant_seed = _derive_seed(config.seed, 1)
        self._payment_seed = _derive_seed(config.seed, 2)
        self._settlement_seed = _derive_seed(config.seed, 3)
        self._bank_seed = _derive_seed(config.seed, 4)
        self._ledger_seed = _derive_seed(config.seed, 5)
        self._corrupt_seed = _derive_seed(config.seed, 6)

    def build_clean(self) -> CleanWorld:
        """Build the clean world. Call once; do not mutate the result."""
        merchants = make_merchants(self.config, self._merchant_seed)
        payments = make_payments(self.config, merchants, self._payment_seed)
        settlements = make_settlements(
            self.config, payments, merchants, self._settlement_seed
        )
        bank_entries = make_bank_entries(
            self.config, settlements, merchants, self._bank_seed
        )
        ledger_entries = make_ledger_entries(
            self.config, payments, settlements, bank_entries, self._ledger_seed
        )
        return CleanWorld(
            merchants=merchants,
            payments=payments,
            settlements=settlements,
            bank_entries=bank_entries,
            ledger_entries=ledger_entries,
        )

    def corrupt(self, clean: CleanWorld) -> ObservedWorld:
        """
        Apply controlled corruption to deep copies of clean world entities.
        INVARIANT: clean is never mutated.
        """
        rng = random.Random(self._corrupt_seed)  # noqa: S311
        cfg = self.config.corruption

        # Deep copy mutable entity lists — never touch clean
        obs_settlements: list[Settlement] = copy.deepcopy(clean.settlements)
        obs_bank_entries: list[BankEntry] = copy.deepcopy(clean.bank_entries)
        obs_ledger_entries: list[LedgerEntry] = copy.deepcopy(clean.ledger_entries)

        # Build lookup maps for observed world
        payment_to_settlement: dict[str, Settlement] = {}
        for s in obs_settlements:
            for pid in s.payment_ids:
                payment_to_settlement[pid] = s

        settlement_ref_to_bank: dict[str, BankEntry] = {
            b.settlement_ref: b for b in obs_bank_entries
        }

        payment_to_ledger: dict[str, LedgerEntry] = {
            le.payment_id: le for le in obs_ledger_entries
        }

        # Corruption type assignment per payment
        corruption_types = _build_corruption_schedule(
            len(clean.payments), cfg, rng
        )

        ground_truth: list[GroundTruth] = []
        corruption_events: list[CorruptionEvent] = []

        # Build clean allocated-amount lookup for GroundTruth (payment-level)
        payment_to_clean_allocated: dict[str, Decimal] = {
            le.payment_id: le.allocated_amount for le in clean.ledger_entries
        }

        # Sets for tracking removed records
        removed_settlement_ids: set[str] = set()
        removed_bank_ids: set[str] = set()
        removed_ledger_ids: set[str] = set()

        # HIGH-1: Guard against double-corruption of the same bank entry.
        # Multiple payments in the same settlement batch share one bank entry.
        # Once a bank entry has been targeted by any corruption, it must not
        # be targeted again — the second event's original_value would reflect
        # the already-corrupted state, making ground truth inaccurate.
        corrupted_bank_ids: set[str] = set()

        ce_counter = 1

        for i, payment in enumerate(clean.payments):
            pid = payment.payment_id
            corruption_type = corruption_types[i]
            ce_id = f"CE_{clean.payments[0].payment_date.strftime('%Y%m%d')}_{ce_counter:04d}"

            if corruption_type == "clean":
                gt = GroundTruth(
                    ground_truth_id=f"GT_{payment.payment_date.strftime('%Y%m%d')}_{i + 1:04d}",
                    payment_id=pid,
                    expected_decision="AUTO_MATCH",
                    discrepancy_type=None,
                    discrepancy_code=None,
                    corruption_id=None,
                    injected_layer=None,
                    clean_settlement_net_amount=None,
                    clean_allocated_amount=None,
                    notes="Clean case — no corruption applied.",
                )
                ground_truth.append(gt)
                continue

            # -- Corruption cases --
            settlement = payment_to_settlement.get(pid)
            bank_entry = (
                settlement_ref_to_bank.get(settlement.settlement_ref)
                if settlement
                else None
            )
            ledger_entry = payment_to_ledger.get(pid)

            event: CorruptionEvent | None = None
            decision = "HUMAN_REVIEW"
            code_map = {
                "missing_settlement": "E001",
                "missing_bank_entry": "E002",
                "missing_ledger_entry": "E003",
                "amount_mismatch": "E004",
                "date_mismatch": "E005",
                "duplicate_bank_entry": "E006",
                "settlement_fee_variance": "E007",
                "orphan_bank_entry": "E008",
            }

            # Per-event deterministic seed (CRIT-1)
            event_seed = derive_event_seed(self._corrupt_seed, ce_counter)

            if corruption_type == "missing_settlement" and settlement:
                _, event = corrupt_missing_settlement(
                    pid, settlement, event_seed, ce_id
                )
                removed_settlement_ids.add(settlement.settlement_id)

            elif corruption_type == "missing_bank_entry" and bank_entry:
                if bank_entry.bank_entry_id in corrupted_bank_ids:
                    event = None  # skip — bank entry already corrupted
                else:
                    _, event = corrupt_missing_bank_entry(
                        pid, bank_entry, event_seed, ce_id
                    )
                    removed_bank_ids.add(bank_entry.bank_entry_id)
                    corrupted_bank_ids.add(bank_entry.bank_entry_id)

            elif corruption_type == "missing_ledger_entry" and ledger_entry:
                _, event = corrupt_missing_ledger_entry(
                    pid, ledger_entry, event_seed, ce_id
                )
                removed_ledger_ids.add(ledger_entry.ledger_entry_id)

            elif corruption_type == "amount_mismatch" and bank_entry:
                if bank_entry.bank_entry_id in corrupted_bank_ids:
                    event = None  # skip — bank entry already corrupted
                else:
                    corrupted_be, event = corrupt_amount_mismatch(
                        pid, bank_entry, event_seed, ce_id
                    )
                    for j, be in enumerate(obs_bank_entries):
                        if be.bank_entry_id == bank_entry.bank_entry_id:
                            obs_bank_entries[j] = corrupted_be
                            settlement_ref_to_bank[corrupted_be.settlement_ref] = corrupted_be
                            break
                    corrupted_bank_ids.add(bank_entry.bank_entry_id)

            elif corruption_type == "date_mismatch" and bank_entry:
                if bank_entry.bank_entry_id in corrupted_bank_ids:
                    event = None  # skip — bank entry already corrupted
                else:
                    # E005: pass payment_date so the clamp (CC-2) can apply
                    corrupted_be, event = corrupt_date_mismatch(
                        pid, bank_entry, event_seed, ce_id,
                        payment_date=payment.payment_date,
                        settlement_date=settlement.settlement_date if settlement else None,
                    )
                    for j, be in enumerate(obs_bank_entries):
                        if be.bank_entry_id == bank_entry.bank_entry_id:
                            obs_bank_entries[j] = corrupted_be
                            settlement_ref_to_bank[corrupted_be.settlement_ref] = corrupted_be
                            break
                    corrupted_bank_ids.add(bank_entry.bank_entry_id)

            elif corruption_type == "duplicate_bank_entry" and bank_entry:
                if bank_entry.bank_entry_id in corrupted_bank_ids:
                    event = None  # skip — bank entry already corrupted
                else:
                    dup, event = corrupt_duplicate_bank_entry(
                        pid, bank_entry, event_seed, ce_id
                    )
                    obs_bank_entries.append(dup)
                    corrupted_bank_ids.add(bank_entry.bank_entry_id)

            elif corruption_type == "settlement_fee_variance" and settlement:
                # E007: returns 3-tuple; sync bank credit to new net (CRIT-2)
                corrupted_s, corrupted_bank, event = corrupt_settlement_fee_variance(
                    pid, settlement, bank_entry, event_seed, ce_id
                )
                for j, s in enumerate(obs_settlements):
                    if s.settlement_id == settlement.settlement_id:
                        obs_settlements[j] = corrupted_s
                        payment_to_settlement[pid] = corrupted_s
                        break
                if corrupted_bank is not None:
                    for j, be in enumerate(obs_bank_entries):
                        if be.bank_entry_id == corrupted_bank.bank_entry_id:
                            obs_bank_entries[j] = corrupted_bank
                            settlement_ref_to_bank[corrupted_bank.settlement_ref] = corrupted_bank
                            break

            elif corruption_type == "orphan_bank_entry":
                ref_bank = obs_bank_entries[0] if obs_bank_entries else bank_entry
                if ref_bank:
                    orphan, event = corrupt_orphan_bank_entry(
                        pid, ref_bank, event_seed, ce_id
                    )
                    obs_bank_entries.append(orphan)
                else:
                    corruption_type = "clean"

            # If no event was produced (prerequisites missing), treat as clean
            if event is None:
                gt = GroundTruth(
                    ground_truth_id=f"GT_{payment.payment_date.strftime('%Y%m%d')}_{i + 1:04d}",
                    payment_id=pid,
                    expected_decision="AUTO_MATCH",
                    discrepancy_type=None,
                    discrepancy_code=None,
                    corruption_id=None,
                    injected_layer=None,
                    clean_settlement_net_amount=None,
                    clean_allocated_amount=None,
                    notes="Corruption skipped — prerequisites missing; treated as clean.",
                )
                ground_truth.append(gt)
                continue

            corruption_events.append(event)
            ce_counter += 1

            # Normalise injected_layer: bank_entry -> bank, ledger_entry -> ledger
            raw_entity = event.target_entity
            injected_layer = raw_entity.replace("_entry", "") if "_entry" in raw_entity else raw_entity

            gt = GroundTruth(
                ground_truth_id=f"GT_{payment.payment_date.strftime('%Y%m%d')}_{i + 1:04d}",
                payment_id=pid,
                expected_decision=decision,
                discrepancy_type=corruption_type,
                discrepancy_code=code_map.get(corruption_type),
                corruption_id=ce_id,
                injected_layer=injected_layer,
                clean_settlement_net_amount=(
                    settlement.net_amount if settlement else None
                ),
                clean_allocated_amount=payment_to_clean_allocated.get(pid),
                notes=f"Corruption: {corruption_type} on {event.target_entity} {event.target_record_id}",
            )
            ground_truth.append(gt)

        # Apply removals
        final_settlements = [
            s for s in obs_settlements if s.settlement_id not in removed_settlement_ids
        ]
        final_bank_entries = [
            b for b in obs_bank_entries if b.bank_entry_id not in removed_bank_ids
        ]
        final_ledger_entries = [
            le for le in obs_ledger_entries if le.ledger_entry_id not in removed_ledger_ids
        ]

        return ObservedWorld(
            merchants=clean.merchants,          # reference data — unchanged
            payments=clean.payments,            # payment is the anchor — unchanged
            settlements=final_settlements,
            bank_entries=final_bank_entries,
            ledger_entries=final_ledger_entries,
            ground_truth=ground_truth,
            corruption_events=corruption_events,
        )


def _build_corruption_schedule(
    n_payments: int,
    cfg,
    rng: random.Random,
) -> list[str]:
    """
    Assign a corruption type (or 'clean') to each payment index.
    Uses floor-count assignment to ensure exact count proportions.
    """
    type_names = [
        "missing_settlement",
        "missing_bank_entry",
        "missing_ledger_entry",
        "amount_mismatch",
        "date_mismatch",
        "duplicate_bank_entry",
        "settlement_fee_variance",
        "orphan_bank_entry",
    ]
    rates = [
        cfg.missing_settlement,
        cfg.missing_bank_entry,
        cfg.missing_ledger_entry,
        cfg.amount_mismatch,
        cfg.date_mismatch,
        cfg.duplicate_bank_entry,
        cfg.settlement_fee_variance,
        cfg.orphan_bank_entry,
    ]

    schedule = ["clean"] * n_payments
    used = 0

    for name, rate in zip(type_names, rates):
        count = int(n_payments * rate)
        for j in range(used, used + count):
            if j < n_payments:
                schedule[j] = name
        used += count

    # Shuffle deterministically
    rng.shuffle(schedule)
    return schedule


def generate(config: DatasetConfig) -> tuple[CleanWorld, ObservedWorld]:
    """
    Full generation pipeline.
    Returns (clean_world, observed_world).
    clean_world is never mutated after return.
    """
    builder = WorldBuilder(config)
    clean = builder.build_clean()
    observed = builder.corrupt(clean)
    return clean, observed
