"""
LedgerLens Phase 3 — Decision Engine
======================================
Orchestrates the full matching cascade for a list of CanonicalTransactions
and produces per-payment EvidenceCard + ReconciliationDecision.

Also processes Fix 2 (duplicate bank entries) and Fix 4 (orphan records)
from the NormaliserResult.

CASCADE ORDER:
  Stage 1 — Exact match  (exact.py)
    → AUTO_MATCH if all rules pass (confidence = 1.00)
    → ABSTAIN   if no settlement at all (is_no_candidate)
    → continue to Stage 2 otherwise

  Stage 2 — Composite scoring  (composite.py)
    → score computed, evidence produced
    → HUMAN_REVIEW if at least one signal matched (has_any_signal)
    → ABSTAIN      if no signal matched at all

  Stage 3+ — Fuzzy / Agent (Phase 4 — DEFERRED)

DECISION RULES (Phase 3.1):
  AUTO_MATCH   — exact match: all rules including R012 temporal and R013 duplicate passed
  HUMAN_REVIEW — exact match found discrepancies OR composite has evidence
  ABSTAIN      — no settlement OR composite has no signal at all

  TBD — REQUIRES SPECIFICATION:
    Numeric thresholds for promoting composite HIGH-score to AUTO_MATCH.
    Phase 3.1 intentionally does NOT apply unspecified thresholds.

FIX 2 — Duplicate bank entries:
  The normaliser identifies duplicate bank entries (multiple entries sharing
  the same settlement_ref). The engine:
    1. Sets has_duplicate_bank_entry=True on the affected CanonicalTransaction
       so R013 blocks AUTO_MATCH.
    2. Creates an ExceptionRecord with rec:E003 for each affected payment.
    3. Adds duplicate entry IDs to alternative_candidate_ids in the EvidenceCard.

FIX 4 — Orphan record processing:
  After per-payment reconciliation, the engine processes orphan records
  from NormaliserResult and creates OrphanRecord entries in BatchReconciliationResult.

DETERMINISM GUARANTEE:
  - Input canonical list must be pre-sorted by payment_id (normaliser does this).
  - All comparisons are value-based (Decimal, str, date).
  - No random, no wall-clock in logic paths.
  - processed_at timestamp set once per batch, passed in externally so tests
    can provide a fixed value for byte-exact comparison.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from app.core.reconciliation.composite import score_composite
from app.core.reconciliation.exact import run_exact_match
from app.core.reconciliation.normaliser import NormaliserResult
from app.data.generator.models import BankEntry, LedgerEntry, Settlement
from app.models.canonical import CanonicalTransaction
from app.models.decisions import (
    BatchReconciliationResult,
    EvidenceCard,
    MatchEvidence,
    OrphanRecord,
    ReconciliationDecision,
)
from app.models.exceptions import ExceptionRecord, REC_E001, REC_E003, REC_E008, REC_E010

_ZERO = Decimal("0")
_ONE = Decimal("1.00")
_TWO_PLACES = Decimal("0.01")


def reconcile_from_normaliser(
    norm_result: NormaliserResult,
    batch_id: str,
    now: datetime | None = None,
) -> tuple[BatchReconciliationResult, list[ExceptionRecord]]:
    """
    Full reconciliation from a NormaliserResult.

    Handles:
      - Per-payment exact + composite matching
      - Fix 2: duplicate bank entries flagged and routed
      - Fix 4: orphan records surfaced as OrphanRecord entries

    Parameters
    ----------
    norm_result:
        Output of normaliser.normalise().
    batch_id:
        Stable identifier for this batch run.
    now:
        UTC timestamp injected for testability. Defaults to utcnow().
        Never affects matching or scoring.

    Returns
    -------
    (BatchReconciliationResult, list[ExceptionRecord])
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    # ------------------------------------------------------------------
    # Fix 2: build set of settlement_refs that have duplicate bank entries
    # so we can flag the affected canonical transactions before matching.
    # ------------------------------------------------------------------
    duplicate_settlement_refs: set[str] = {
        b.settlement_ref for b in norm_result.duplicate_bank_entries
    }
    # Map settlement_ref → list of duplicate bank_entry_ids (for EvidenceCard)
    dup_ref_to_ids: dict[str, list[str]] = {}
    for b in norm_result.duplicate_bank_entries:
        dup_ref_to_ids.setdefault(b.settlement_ref, []).append(b.bank_entry_id)

    # ------------------------------------------------------------------
    # Build augmented canonical list with has_duplicate_bank_entry set
    # ------------------------------------------------------------------
    augmented: list[CanonicalTransaction] = []
    for ct in norm_result.canonical_transactions:
        if ct.settlement_ref and ct.settlement_ref in duplicate_settlement_refs:
            # Replace frozen model with updated copy
            ct = ct.model_copy(update={"has_duplicate_bank_entry": True})
        augmented.append(ct)

    # ------------------------------------------------------------------
    # Per-payment reconciliation
    # ------------------------------------------------------------------
    decisions: list[ReconciliationDecision] = []
    evidence_cards: list[EvidenceCard] = []
    exceptions: list[ExceptionRecord] = []

    auto_matched = 0
    human_review = 0
    abstained = 0

    for seq, ct in enumerate(augmented, start=1):
        audit_id = _make_audit_id(ct, seq)
        exc_id = _make_exc_id(ct, seq)

        # Alternative candidate IDs for EvidenceCard (Fix 7)
        alt_ids: list[str] = []
        if ct.settlement_ref and ct.settlement_ref in dup_ref_to_ids:
            alt_ids = dup_ref_to_ids[ct.settlement_ref]

        card, decision, maybe_exc = _reconcile_one(
            ct=ct,
            audit_id=audit_id,
            exc_id=exc_id,
            now=now,
            alternative_candidate_ids=alt_ids,
        )

        evidence_cards.append(card)
        decisions.append(decision)
        if maybe_exc is not None:
            exceptions.append(maybe_exc)

        if decision.decision == "AUTO_MATCH":
            auto_matched += 1
        elif decision.decision == "HUMAN_REVIEW":
            human_review += 1
        else:
            abstained += 1

    # ------------------------------------------------------------------
    # Fix 4: Build OrphanRecord entries from normaliser result
    # ------------------------------------------------------------------
    orphan_records = _build_orphan_records(norm_result, seq_start=len(augmented) + 1, now=now)

    total = len(augmented)
    match_rate = (
        (Decimal(auto_matched) / Decimal(total)).quantize(_TWO_PLACES)
        if total > 0 else _ZERO
    )
    exception_rate = (
        (Decimal(human_review + abstained) / Decimal(total)).quantize(_TWO_PLACES)
        if total > 0 else _ZERO
    )

    result = BatchReconciliationResult(
        batch_id=batch_id,
        total_records=total,
        auto_matched=auto_matched,
        human_review=human_review,
        abstained=abstained,
        decisions=decisions,
        evidence_cards=evidence_cards,
        orphan_records=orphan_records,
        match_rate=match_rate,
        exception_rate=exception_rate,
        processed_at=now,
    )
    return result, exceptions


def reconcile_batch(
    canonical_list: Sequence[CanonicalTransaction],
    batch_id: str,
    now: datetime | None = None,
) -> tuple[BatchReconciliationResult, list[ExceptionRecord]]:
    """
    Reconcile a pre-normalised, pre-sorted list of CanonicalTransactions.

    Compatibility entry point for callers that do not use NormaliserResult.
    Duplicate and orphan detection is not available via this path — use
    reconcile_from_normaliser() for full functionality.
    """
    from app.core.reconciliation.normaliser import NormaliserResult

    norm = NormaliserResult(canonical_transactions=list(canonical_list))
    return reconcile_from_normaliser(norm, batch_id=batch_id, now=now)


# ---------------------------------------------------------------------------
# Per-payment reconciliation
# ---------------------------------------------------------------------------

def _reconcile_one(
    ct: CanonicalTransaction,
    audit_id: str,
    exc_id: str,
    now: datetime,
    alternative_candidate_ids: list[str] | None = None,
) -> tuple[EvidenceCard, ReconciliationDecision, ExceptionRecord | None]:
    """Run the matching cascade for one payment and return its outputs."""

    alt_ids = alternative_candidate_ids or []

    # ----------------------------------------------------------------
    # Run post-match validation rules (temporal checks)
    # ----------------------------------------------------------------
    from app.core.reconciliation.validation import run_validation
    validation_findings = run_validation(ct)
    failed_findings = [f for f in validation_findings if not f.passed]
    has_timing_anomaly = any(f.severity in ("WARNING", "ERROR") for f in failed_findings)
    validation_codes = sorted(list({f.discrepancy_code for f in failed_findings if f.discrepancy_code}))

    # ----------------------------------------------------------------
    # Stage 1 — Exact matching
    # ----------------------------------------------------------------
    exact_result = run_exact_match(ct)

    if exact_result.is_match:
        if has_timing_anomaly:
            # Structurally matched, but timing validation failed -> HUMAN_REVIEW
            card = EvidenceCard(
                audit_id=audit_id,
                payment_id=ct.payment_id,
                decision="HUMAN_REVIEW",
                confidence=_ONE,  # Keep structural confidence separate (1.00)
                matched_settlement_id=ct.settlement_id,
                matched_bank_entry_id=ct.bank_entry_id,
                matched_ledger_entry_id=ct.ledger_entry_id,
                evidence=exact_result.evidence,
                rules_triggered=[e.rule_id for e in exact_result.evidence if e.matched],
                stage_reached="exact",
                discrepancy_codes=validation_codes,
                notes="Structurally matched but post-match temporal validation failed.",
                amount_delta=exact_result.amount_delta,
                date_delta_days=exact_result.date_delta_days,
                alternative_candidate_ids=alt_ids,
                validation_findings=validation_findings,
                processed_at=now,
            )
            decision = ReconciliationDecision(
                payment_id=ct.payment_id,
                decision="HUMAN_REVIEW",
                confidence=_ONE,
                exception_codes=validation_codes,
                audit_id=audit_id,
            )
            exc = ExceptionRecord(
                exception_id=exc_id,
                payment_id=ct.payment_id,
                exception_codes=validation_codes or [REC_E010],
                status="DETECTED",
                audit_id=audit_id,
                created_at=now,
                notes="Temporal validation failed on structurally matched transaction.",
            )
            return card, decision, exc
        else:
            # Perfect exact match + clean validation -> AUTO_MATCH
            card = EvidenceCard(
                audit_id=audit_id,
                payment_id=ct.payment_id,
                decision="AUTO_MATCH",
                confidence=_ONE,
                matched_settlement_id=ct.settlement_id,
                matched_bank_entry_id=ct.bank_entry_id,
                matched_ledger_entry_id=ct.ledger_entry_id,
                evidence=exact_result.evidence,
                rules_triggered=[e.rule_id for e in exact_result.evidence if e.matched],
                stage_reached="exact",
                discrepancy_codes=[],
                notes="Exact match: all structural, financial, and temporal checks passed.",
                amount_delta=exact_result.amount_delta,
                date_delta_days=exact_result.date_delta_days,
                alternative_candidate_ids=alt_ids,
                validation_findings=validation_findings,
                processed_at=now,
            )
            decision = ReconciliationDecision(
                payment_id=ct.payment_id,
                decision="AUTO_MATCH",
                confidence=_ONE,
                exception_codes=[],
                audit_id=audit_id,
            )
            return card, decision, None

    if exact_result.is_no_candidate:
        card = EvidenceCard(
            audit_id=audit_id,
            payment_id=ct.payment_id,
            decision="ABSTAIN",
            confidence=_ZERO,
            matched_settlement_id=None,
            matched_bank_entry_id=None,
            matched_ledger_entry_id=None,
            evidence=exact_result.evidence,
            rules_triggered=[],
            stage_reached="no_match",
            discrepancy_codes=exact_result.discrepancy_codes,
            notes="No settlement found — ABSTAIN (insufficient evidence).",
            amount_delta=None,
            date_delta_days=None,
            alternative_candidate_ids=alt_ids,
            validation_findings=validation_findings,
            processed_at=now,
        )
        decision = ReconciliationDecision(
            payment_id=ct.payment_id,
            decision="ABSTAIN",
            confidence=_ZERO,
            exception_codes=exact_result.discrepancy_codes,
            audit_id=audit_id,
        )
        exc = ExceptionRecord(
            exception_id=exc_id,
            payment_id=ct.payment_id,
            exception_codes=exact_result.discrepancy_codes or [REC_E010],
            status="DETECTED",
            audit_id=audit_id,
            created_at=now,
            notes="No settlement candidate found.",
        )
        return card, decision, exc

    # ----------------------------------------------------------------
    # Stage 2 — Composite scoring
    # ----------------------------------------------------------------
    composite = score_composite(ct)

    all_evidence = list(exact_result.evidence) + list(composite.signals)
    all_triggered = [e.rule_id for e in all_evidence if e.matched]
    all_codes = sorted(list(set(exact_result.discrepancy_codes + validation_codes)))

    if composite.has_any_signal:
        card = EvidenceCard(
            audit_id=audit_id,
            payment_id=ct.payment_id,
            decision="HUMAN_REVIEW",
            confidence=composite.score,
            matched_settlement_id=ct.settlement_id,
            matched_bank_entry_id=ct.bank_entry_id,
            matched_ledger_entry_id=ct.ledger_entry_id,
            evidence=all_evidence,
            rules_triggered=all_triggered,
            stage_reached="composite",
            discrepancy_codes=all_codes,
            notes=(
                f"Exact match failed; composite score={composite.score}. "
                "HUMAN_REVIEW required."
            ),
            amount_delta=exact_result.amount_delta,
            date_delta_days=exact_result.date_delta_days,
            alternative_candidate_ids=alt_ids,
            validation_findings=validation_findings,
            processed_at=now,
        )
        decision = ReconciliationDecision(
            payment_id=ct.payment_id,
            decision="HUMAN_REVIEW",
            confidence=composite.score,
            exception_codes=all_codes,
            audit_id=audit_id,
        )
        exc = ExceptionRecord(
            exception_id=exc_id,
            payment_id=ct.payment_id,
            exception_codes=all_codes or [REC_E010],
            status="DETECTED",
            audit_id=audit_id,
            created_at=now,
            notes=f"Composite score={composite.score}; requires human review.",
        )
        return card, decision, exc

    else:
        all_codes_abstain = all_codes or [REC_E010]
        card = EvidenceCard(
            audit_id=audit_id,
            payment_id=ct.payment_id,
            decision="ABSTAIN",
            confidence=_ZERO,
            matched_settlement_id=None,
            matched_bank_entry_id=None,
            matched_ledger_entry_id=None,
            evidence=all_evidence,
            rules_triggered=all_triggered,
            stage_reached="composite",
            discrepancy_codes=all_codes_abstain,
            notes="No composite signals matched — ABSTAIN (insufficient evidence).",
            amount_delta=exact_result.amount_delta,
            date_delta_days=exact_result.date_delta_days,
            alternative_candidate_ids=alt_ids,
            validation_findings=validation_findings,
            processed_at=now,
        )
        decision = ReconciliationDecision(
            payment_id=ct.payment_id,
            decision="ABSTAIN",
            confidence=_ZERO,
            exception_codes=all_codes_abstain,
            audit_id=audit_id,
        )
        exc = ExceptionRecord(
            exception_id=exc_id,
            payment_id=ct.payment_id,
            exception_codes=all_codes_abstain,
            status="DETECTED",
            audit_id=audit_id,
            created_at=now,
            notes="No composite signals matched.",
        )
        return card, decision, exc



# ---------------------------------------------------------------------------
# Fix 4 — Orphan record builder
# ---------------------------------------------------------------------------

def _build_orphan_records(
    norm_result: NormaliserResult,
    seq_start: int,
    now: datetime,
) -> list[OrphanRecord]:
    """
    Build OrphanRecord entries for all orphan entities in the NormaliserResult.

    Orphan bank entries    → rec:E008 (Unknown transaction)
    Orphan settlements     → rec:E010 (Insufficient evidence)
    Orphan ledger entries  → rec:E010 (Insufficient evidence)
    """
    orphans: list[OrphanRecord] = []
    seq = seq_start

    for b in norm_result.orphan_bank_entries:
        date_str = b.value_date.strftime("%Y%m%d")
        orphans.append(OrphanRecord(
            orphan_id=f"ORF_{date_str}_{seq:04d}",
            entity_type="bank_entry",
            entity_id=b.bank_entry_id,
            unmatched_ref=b.settlement_ref,
            exception_code=REC_E008,
            notes=(
                f"Orphan bank entry: settlement_ref '{b.settlement_ref}' "
                "not found in any settlement record."
            ),
        ))
        seq += 1

    for s in norm_result.orphan_settlements:
        date_str = s.settlement_date.strftime("%Y%m%d")
        orphans.append(OrphanRecord(
            orphan_id=f"ORF_{date_str}_{seq:04d}",
            entity_type="settlement",
            entity_id=s.settlement_id,
            unmatched_ref=s.settlement_ref,
            exception_code=REC_E010,
            notes=(
                f"Orphan settlement: none of payment_ids {s.payment_ids} "
                "exist in the current batch."
            ),
        ))
        seq += 1

    for le in norm_result.orphan_ledger_entries:
        date_str = le.posting_date.strftime("%Y%m%d")
        orphans.append(OrphanRecord(
            orphan_id=f"ORF_{date_str}_{seq:04d}",
            entity_type="ledger_entry",
            entity_id=le.ledger_entry_id,
            unmatched_ref=le.payment_id,
            exception_code=REC_E010,
            notes=(
                f"Orphan ledger entry: payment_id '{le.payment_id}' "
                "not found in any payment record."
            ),
        ))
        seq += 1

    return orphans


# ---------------------------------------------------------------------------
# ID generators (deterministic)
# ---------------------------------------------------------------------------

def _make_audit_id(ct: CanonicalTransaction, seq: int) -> str:
    date_str = ct.payment_date.strftime("%Y%m%d")
    return f"AUD_{date_str}_{seq:04d}"


def _make_exc_id(ct: CanonicalTransaction, seq: int) -> str:
    date_str = ct.payment_date.strftime("%Y%m%d")
    return f"EXC_{date_str}_{seq:04d}"
