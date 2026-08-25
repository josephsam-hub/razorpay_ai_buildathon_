"""
LedgerLens Phase 3.2 — Batch Integrity Analysis
================================================
Classifies each settlement batch into integrity finding codes.

A batch = one settlement record covering 1–5 payments + one bank entry
+ multiple ledger entries (one per payment in the batch).

FINDING CODES (plan §8, Revision 7):
  BATCH_CLEAN             All payments AUTO_MATCH; no orphans/duplicates/anomalies
  BATCH_PARTIAL           Some payments resolved, some not
  BATCH_ORPHAN_ENTITY     Orphan entity detected within this batch's settlement_ref scope
  BATCH_DUPLICATE_ENTITY  Duplicate bank entry detected for this batch
  BATCH_MISSING_SETTLEMENT Settlement absent — no anchor
  BATCH_TEMPORAL_ANOMALY  All payments matched but temporal validation (V001–V004) failed

KEY CLAIM PREVENTION:
  The final report MUST NOT claim "100% reconciliation" if any batch is non-BATCH_CLEAN.
  fully_reconciled_rate != auto_match_rate (plan §8).

IMPORT RULE: Does NOT import from app.core.reconciliation.* directly.
Receives pre-processed data from the evaluator.
"""

from __future__ import annotations

from app.models.decisions import BatchReconciliationResult, EvidenceCard
from app.models.evaluation import BatchFinding, BatchIntegrityResult, BatchIntegrityScorecard
from app.core.evaluation.metrics import compute_fully_reconciled_rate


def analyse_batch_integrity(
    result: BatchReconciliationResult,
    settlement_payment_map: dict[str, list[str]],
    settlement_ref_map: dict[str, str],
) -> tuple[list[BatchIntegrityResult], BatchIntegrityScorecard]:
    """
    Analyse batch integrity for every settlement batch in the result.

    Parameters
    ----------
    result:
        BatchReconciliationResult from the reconciliation engine.
    settlement_payment_map:
        settlement_id → list of payment_ids belonging to that settlement.
        Built from the observed world settlements.
    settlement_ref_map:
        payment_id → settlement_ref for each payment.
        Used to link orphan records back to their batch scope.

    Returns
    -------
    (list[BatchIntegrityResult], BatchIntegrityScorecard)
    """
    # Index engine decisions by payment_id
    decision_map = {d.payment_id: d for d in result.decisions}

    # Index evidence cards by payment_id (for temporal anomaly detection)
    card_map = {c.payment_id: c for c in result.evidence_cards}

    # Index orphan records by settlement_ref scope
    orphan_refs: set[str] = set()
    for orp in result.orphan_records:
        if orp.entity_type == "bank_entry":
            orphan_refs.add(orp.unmatched_ref)  # unmatched_ref = settlement_ref of orphan

    # Build set of settlement_refs that have duplicates
    # (payments with rec:E003 in exception_codes)
    dup_settlement_refs: set[str] = set()
    for d in result.decisions:
        if "rec:E003" in d.exception_codes:
            ref = settlement_ref_map.get(d.payment_id)
            if ref:
                dup_settlement_refs.add(ref)

    batch_results: list[BatchIntegrityResult] = []

    # Process each known settlement batch
    for settlement_id, payment_ids in sorted(settlement_payment_map.items()):
        if not payment_ids:
            continue

        # Gather decisions for all payments in this batch
        batch_decisions = [decision_map[pid] for pid in payment_ids if pid in decision_map]
        missing_payments = [pid for pid in payment_ids if pid not in decision_map]

        n_auto = sum(1 for d in batch_decisions if d.decision == "AUTO_MATCH")
        n_hr = sum(1 for d in batch_decisions if d.decision == "HUMAN_REVIEW")
        n_ab = sum(1 for d in batch_decisions if d.decision == "ABSTAIN")

        findings: list[BatchFinding] = []

        # Get settlement_ref for this batch (from first payment)
        batch_ref = None
        for pid in payment_ids:
            batch_ref = settlement_ref_map.get(pid)
            if batch_ref:
                break

        # Check for orphan entities in this batch's scope
        has_orphan = batch_ref is not None and batch_ref in orphan_refs
        if has_orphan:
            findings.append("BATCH_ORPHAN_ENTITY")

        # Check for duplicate bank entry in this batch
        has_dup = batch_ref is not None and batch_ref in dup_settlement_refs
        if has_dup:
            findings.append("BATCH_DUPLICATE_ENTITY")

        # Check for temporal anomalies (V001–V004 failures on any payment in batch)
        has_temporal = False
        for pid in payment_ids:
            card = card_map.get(pid)
            if card and card.validation_findings:
                if any(not f.passed for f in card.validation_findings):
                    has_temporal = True
                    break
        if has_temporal:
            findings.append("BATCH_TEMPORAL_ANOMALY")

        # Check if settlement is missing (all payments ABSTAIN with rec:E001)
        all_abstain_missing = (
            len(batch_decisions) > 0
            and all(d.decision == "ABSTAIN" for d in batch_decisions)
            and all("rec:E001" in d.exception_codes for d in batch_decisions)
        )
        if all_abstain_missing:
            findings.append("BATCH_MISSING_SETTLEMENT")

        # Check partial resolution
        total = len(payment_ids)
        resolved = n_auto
        if 0 < resolved < total and "BATCH_MISSING_SETTLEMENT" not in findings:
            findings.append("BATCH_PARTIAL")

        # If no other findings and all AUTO_MATCH and no orphan/dup/temporal → CLEAN
        if not findings and n_auto == total and not has_orphan and not has_dup and not has_temporal:
            findings.append("BATCH_CLEAN")
        elif not findings:
            # Some HR/ABSTAIN but no specific finding tagged yet → PARTIAL
            findings.append("BATCH_PARTIAL")

        batch_results.append(
            BatchIntegrityResult(
                settlement_id=settlement_id,
                settlement_ref=batch_ref,
                payment_ids=payment_ids,
                findings=findings,
                total_payments_in_batch=len(payment_ids),
                auto_matched_in_batch=n_auto,
                human_review_in_batch=n_hr,
                abstained_in_batch=n_ab,
                has_orphan_entity=has_orphan,
                has_duplicate_entity=has_dup,
                has_temporal_anomaly=has_temporal,
            )
        )

    # Count findings across all batches
    total_batches = len(batch_results)
    clean = sum(1 for b in batch_results if "BATCH_CLEAN" in b.findings)
    partial = sum(1 for b in batch_results if "BATCH_PARTIAL" in b.findings)
    orphan_b = sum(1 for b in batch_results if "BATCH_ORPHAN_ENTITY" in b.findings)
    dup_b = sum(1 for b in batch_results if "BATCH_DUPLICATE_ENTITY" in b.findings)
    missing_b = sum(1 for b in batch_results if "BATCH_MISSING_SETTLEMENT" in b.findings)
    temporal_b = sum(1 for b in batch_results if "BATCH_TEMPORAL_ANOMALY" in b.findings)

    rate, insuff = compute_fully_reconciled_rate(clean, total_batches)

    scorecard = BatchIntegrityScorecard(
        total_batches=total_batches,
        clean_batches=clean,
        partial_batches=partial,
        orphan_entity_batches=orphan_b,
        duplicate_entity_batches=dup_b,
        missing_settlement_batches=missing_b,
        temporal_anomaly_batches=temporal_b,
        fully_reconciled_rate=rate,
        insufficient_data=insuff,
    )

    return batch_results, scorecard
