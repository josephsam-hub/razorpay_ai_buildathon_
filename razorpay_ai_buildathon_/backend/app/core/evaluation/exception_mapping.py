"""
LedgerLens Phase 3.2 — Exception Semantic Mapping
===================================================
Bridges the two separate E-code namespaces:

  Generator codes  E001–E008  (plain, no prefix)  — corruption labels
  Reconciliation   rec:E001–rec:E010 (prefixed)   — engine exception codes

These are DIFFERENT taxonomies. The evaluator uses this bridge to determine
whether the engine produced the right rec: code for a given corruption type.

Source: implementation_plan_phase3_2.md §5 (Revision 3 — Semantic mapping table)

IMPORT RULE: This module MAY be imported by the evaluator.
It MUST NOT be imported by app.core.reconciliation.*.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CorruptionMapping:
    """
    Semantic description of one generator corruption type and how the
    reconciliation engine is expected to detect and classify it.
    """

    gen_code: str                       # "E001"–"E008"
    gen_type: str                       # Python name used in ground_truth.discrepancy_type
    affected_entity: str                # entity layer primarily affected
    observed_manifestation: str         # what the observed world looks like
    detection_mechanism: str            # which rule/validation detects it
    expected_decision: str              # AUTO_MATCH / HUMAN_REVIEW / ABSTAIN
    expected_rec_codes: list[str]       # rec: codes engine should produce
    can_produce_multiple_findings: bool  # whether multiple rec: codes possible
    notes: str                          # special cases / known gaps


# ---------------------------------------------------------------------------
# Semantic mapping table — one entry per generator E-code
# ---------------------------------------------------------------------------

CORRUPTION_MAPPINGS: dict[str, CorruptionMapping] = {

    "missing_settlement": CorruptionMapping(
        gen_code="E001",
        gen_type="missing_settlement",
        affected_entity="settlement",
        observed_manifestation="Settlement row removed from observed settlements list",
        detection_mechanism="R001 fails (settlement absent) → is_no_candidate=True",
        expected_decision="ABSTAIN",
        expected_rec_codes=["rec:E001"],
        can_produce_multiple_findings=False,
        notes="Engine short-circuits at R001: no settlement → ABSTAIN immediately.",
    ),

    "missing_bank_entry": CorruptionMapping(
        gen_code="E002",
        gen_type="missing_bank_entry",
        affected_entity="bank_entry",
        observed_manifestation="Bank entry row removed from observed bank_entries",
        detection_mechanism="R002 fails (bank absent); settlement still present",
        expected_decision="HUMAN_REVIEW",
        expected_rec_codes=["rec:E001"],
        can_produce_multiple_findings=False,
        notes="Settlement present → not is_no_candidate; bank missing → HUMAN_REVIEW.",
    ),

    "missing_ledger_entry": CorruptionMapping(
        gen_code="E003",
        gen_type="missing_ledger_entry",
        affected_entity="ledger_entry",
        observed_manifestation="Ledger entry row removed from observed ledger_entries",
        detection_mechanism="R003 fails (ledger absent)",
        expected_decision="HUMAN_REVIEW",
        expected_rec_codes=["rec:E001"],
        can_produce_multiple_findings=False,
        notes="Settlement and bank still present; ledger missing → HUMAN_REVIEW.",
    ),

    "amount_mismatch": CorruptionMapping(
        gen_code="E004",
        gen_type="amount_mismatch",
        affected_entity="bank_entry",
        observed_manifestation="BankEntry.credit_amount shifted ±2–10% from settlement.net",
        detection_mechanism="R010 fails (bank_credit ≠ settlement_net)",
        expected_decision="HUMAN_REVIEW",
        expected_rec_codes=["rec:E002"],
        can_produce_multiple_findings=False,
        notes="All structural links present; R010 is the primary detector.",
    ),

    "date_mismatch": CorruptionMapping(
        gen_code="E005",
        gen_type="date_mismatch",
        affected_entity="bank_entry",
        observed_manifestation="BankEntry.value_date shifted ±1–5 days (clamped ≥ payment_date)",
        detection_mechanism=(
            "Structural exact match passes (R001–R009, R010 may pass if credit=net). "
            "V003 fails: value_date - settlement_date outside [0,1] days. "
            "V002 may also fire if shift crosses settlement cycle boundary."
        ),
        expected_decision="HUMAN_REVIEW",
        expected_rec_codes=["rec:E004"],
        can_produce_multiple_findings=True,
        notes=(
            "E005 produces structural match + temporal anomaly → HUMAN_REVIEW. "
            "Engine confidence stays 1.00 but validation fails. "
            "V003 is the primary detector. V002 may co-fire (rec:E004 both ways)."
        ),
    ),

    "duplicate_bank_entry": CorruptionMapping(
        gen_code="E006",
        gen_type="duplicate_bank_entry",
        affected_entity="bank_entry",
        observed_manifestation=(
            "Additional BNK row injected with same settlement_ref but different bank_ref. "
            "Original BNK row still present."
        ),
        detection_mechanism=(
            "Normaliser detects duplicate settlement_ref → sets has_duplicate_bank_entry=True. "
            "R013 fires → exact match blocked."
        ),
        expected_decision="HUMAN_REVIEW",
        expected_rec_codes=["rec:E003"],
        can_produce_multiple_findings=False,
        notes=(
            "R013 fires before composite. Payment structural links otherwise intact. "
            "HUMAN_REVIEW with rec:E003."
        ),
    ),

    "settlement_fee_variance": CorruptionMapping(
        gen_code="E007",
        gen_type="settlement_fee_variance",
        affected_entity="settlement",
        observed_manifestation=(
            "Settlement.fee_amount shifted ±1–3% of gross; net_amount adjusted accordingly. "
            "CRIT-2: BankEntry.credit_amount synced to new net — so bank and settlement are "
            "internally consistent in the observed world."
        ),
        detection_mechanism=(
            "KNOWN GAP: R010 PASSES because CRIT-2 kept bank_credit == new settlement_net. "
            "V002 checks date cycle (not fee), so it DOES NOT detect this. "
            "No rule currently compares bank_credit + settlement_fee against payment_amount. "
            "Phase 3.1 engine will likely AUTO_MATCH E007 cases → FP_MATCH."
        ),
        expected_decision="HUMAN_REVIEW",
        expected_rec_codes=["rec:E002"],
        can_produce_multiple_findings=False,
        notes=(
            "PHASE 3.1 KNOWN GAP: E007 likely produces unsafe AUTO_MATCH. "
            "The evaluator will measure and report this. "
            "Fix deferred to Phase 3.3 (R014: bank_credit + fee == payment_amount "
            "for single-payment settlements)."
        ),
    ),

    "orphan_bank_entry": CorruptionMapping(
        gen_code="E008",
        gen_type="orphan_bank_entry",
        affected_entity="bank_entry",
        observed_manifestation=(
            "New BNK row injected with settlement_ref='REF_ORPHAN_CE_*'. "
            "Affected payment's original BNK row is unchanged — payment reconciles normally."
        ),
        detection_mechanism=(
            "Normaliser: orphan BNK settlement_ref not in any settlement → orphan_bank_entries. "
            "Engine creates OrphanRecord with rec:E008. "
            "Payment itself may AUTO_MATCH correctly — evaluated separately."
        ),
        expected_decision="HUMAN_REVIEW",
        expected_rec_codes=["rec:E008"],
        can_produce_multiple_findings=False,
        notes=(
            "E008 is TWO-LEVEL: payment is scored independently (may TP_MATCH), "
            "and the orphan entity is scored separately in the exception scorecard. "
            "A batch with a correctly AUTO_MATCHed payment but an unresolved orphan "
            "is NOT BATCH_CLEAN."
        ),
    ),
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_mapping(gen_type: str) -> CorruptionMapping | None:
    """Return the CorruptionMapping for a generator type name, or None."""
    return CORRUPTION_MAPPINGS.get(gen_type)


def get_expected_rec_codes(gen_type: str) -> list[str]:
    """Return the expected rec: codes for a generator type. Empty list if unknown."""
    m = CORRUPTION_MAPPINGS.get(gen_type)
    return list(m.expected_rec_codes) if m else []


def is_expected_decision(gen_type: str, engine_decision: str) -> bool:
    """
    Return True if the engine decision matches the expected decision
    for this corruption type.

    Note: ABST_CORRUPT is treated as correct for any gen_type because
    abstaining conservatively on a corrupt record is acceptable even if
    not ideal.
    """
    m = CORRUPTION_MAPPINGS.get(gen_type)
    if m is None:
        return False
    if engine_decision == "ABSTAIN":
        # Conservative abstain on corrupt record counts as correct
        return True
    return engine_decision == m.expected_decision


def codes_intersect(engine_codes: list[str], gen_type: str) -> bool:
    """
    Return True if at least one of the engine's rec: codes matches the
    expected codes for this generator type.
    """
    expected = set(get_expected_rec_codes(gen_type))
    return bool(expected.intersection(engine_codes))


# ---------------------------------------------------------------------------
# Partition helpers for seed strategy
# ---------------------------------------------------------------------------

CALIBRATION_SEEDS: tuple[int, ...] = (42, 43, 44, 45, 46)
EVALUATION_SEEDS: tuple[int, ...] = (100, 101, 102, 103, 104)
HOLDOUT_SEED: int = 999  # NEVER use during development; only for final demo


def classify_seed(seed: int) -> str:
    """Return 'calibration', 'evaluation', 'holdout', or 'unknown'."""
    if seed in CALIBRATION_SEEDS:
        return "calibration"
    if seed in EVALUATION_SEEDS:
        return "evaluation"
    if seed == HOLDOUT_SEED:
        return "holdout"
    return "unknown"


def assert_not_holdout(seed: int) -> None:
    """Raise ValueError if seed is the holdout seed."""
    if seed == HOLDOUT_SEED:
        raise ValueError(
            f"Seed {HOLDOUT_SEED} is the holdout seed and must NOT be used "
            "during development or calibration. "
            "Run the holdout only after all policy decisions are frozen."
        )


# ---------------------------------------------------------------------------
# E008 payment-level semantics (Fix A)
# ---------------------------------------------------------------------------

def e008_payment_is_clean(gen_type: str | None) -> bool:
    """
    Return True if the corruption type is 'orphan_bank_entry' (E008).

    For E008, the anchor payment's own reconciliation chain is UNAFFECTED.
    The orphan bank entry has a completely different settlement_ref and is
    resolved at entity level, not payment level.

    Therefore:
      - engine AUTO_MATCH on an E008 anchor payment → TP_MATCH (not FP_MATCH)
      - engine HUMAN_REVIEW / ABSTAIN on E008 payment → FN_MISS_CLEAN (false alarm)

    This reflects the approved plan §4:
      "PAY_001 → AUTO_MATCH is CORRECT (payment reconciliation passes)"
    """
    return gen_type == "orphan_bank_entry"


# ---------------------------------------------------------------------------
# Expected-orphan entity set (Fix B)
# ---------------------------------------------------------------------------

def build_expected_orphan_entity_ids(
    corruption_events,
    observed_world,
) -> set[str]:
    """
    Build the complete set of entity IDs that are legitimately orphaned
    as a result of ANY corruption event (not only E008).

    An entity becomes an expected orphan when:
      (a) It was directly injected as an orphan by E008 corruption.
      (b) Its parent relationship was removed by another corruption type,
          making the engine correctly surface it as unreachable.

    Examples of indirect orphaning:
      E001 (missing_settlement): removes a settlement → the legitimate
        bank entry for that settlement_ref has no reachable settlement →
        the normaliser routes it to orphan_bank_entries. This is expected
        behaviour, NOT a false orphan.
      E002 (missing_bank_entry): bank entry removed, so if the removed
        entry somehow still appears it would be an orphan — but since E002
        removes the entry entirely, nothing appears in orphan_records.

    Parameters
    ----------
    corruption_events : list[CorruptionEvent]
        All corruption events from the observed world.
    observed_world : ObservedWorld
        The observed world (used to find settlement_ref for E001 events).

    Returns
    -------
    set[str]
        Bank entry IDs that are legitimately expected to appear in
        orphan_records. Engine reporting any of these is CORRECT behaviour.
    """
    expected: set[str] = set()

    # (a) Directly injected orphans (E008)
    for ce in corruption_events:
        if ce.corruption_type == "orphan_bank_entry":
            expected.add(ce.target_record_id)

    # (b) Indirectly orphaned: E001 removes a settlement whose bank entry
    #     is legitimate but becomes unreachable.
    #     Find the settlement_ref of each E001-removed settlement, then
    #     find all bank entries for that ref in the observed world.
    e001_removed_settlement_ids: set[str] = {
        ce.target_record_id
        for ce in corruption_events
        if ce.corruption_type == "missing_settlement"
    }
    if e001_removed_settlement_ids:
        # Build settlement_id → settlement_ref map from ALL settlements
        # (including those that were removed — we need the ref for lookup)
        # The settlement is NOT in obs.settlements (it was removed), so
        # use corruption_event.case_id to find the associated bank entry.
        # Strategy: look for bank entries whose settlement_ref resolves to
        # a known-settlement but the settlement is now absent.
        #
        # More robust approach: find bank entries whose settlement_ref
        # is NOT in the observed settlements list (i.e. their parent was removed).
        known_refs: set[str] = {s.settlement_ref for s in observed_world.settlements}
        for b in observed_world.bank_entries:
            if b.settlement_ref not in known_refs and "ORP" not in b.settlement_ref:
                # This bank entry's settlement was removed — it is a legitimate
                # indirect orphan caused by E001.
                expected.add(b.bank_entry_id)

    return expected
