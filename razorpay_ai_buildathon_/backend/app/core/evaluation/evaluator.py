"""
LedgerLens Phase 3.2 — Evaluator
==================================
Core evaluation class. Joins engine output with ground truth to produce
a PerSeedResult containing both scorecards, unsafe auto-match metrics,
batch integrity, and entity-level findings.

GROUND-TRUTH ISOLATION:
  This module receives GroundTruth and CorruptionEvent from the caller.
  It NEVER imports from app.core.reconciliation.*.
  The reconciliation engine MUST NOT import from this module.

IMPORT RULE: app.core.reconciliation.* must not import this module.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal

from app.data.generator.models import CorruptionEvent, GroundTruth
from app.data.generator.world import ObservedWorld
from app.models.decisions import BatchReconciliationResult
from app.models.evaluation import (
    BatchIntegrityScorecard,
    EntityFinding,
    ExceptionScorecard,
    PerCorruptionMetric,
    PerEntityMetric,
    PerSeedResult,
    ReconciliationScorecard,
    ThroughputResult,
    UnsafeAutoMatchMetrics,
)
from app.core.evaluation.exception_mapping import (
    CORRUPTION_MAPPINGS,
    build_expected_orphan_entity_ids,
    codes_intersect,
    e008_payment_is_clean,
    get_expected_rec_codes,
)
from app.core.evaluation.batch_integrity import analyse_batch_integrity
from app.core.evaluation.metrics import (
    compute_auto_match_precision,
    compute_auto_match_recall,
    compute_detection_rate,
    compute_exception_f1,
    compute_exception_precision,
    compute_exception_recall,
    compute_reconciliation_f1,
    compute_resolution_rate,
    compute_unsafe_auto_match_rate,
)

_ZERO = Decimal("0")


class Evaluator:
    """
    Stateless evaluator. Call evaluate() once per seed dataset.

    Never mutates inputs. Ground truth stays strictly inside this layer.
    """

    def evaluate(
        self,
        result: BatchReconciliationResult,
        observed: ObservedWorld,
        seed: int,
        dataset_version: str = "",
        config_hash: str = "",
        throughput: ThroughputResult | None = None,
    ) -> PerSeedResult:
        """
        Evaluate one reconciliation result against the ground truth in the
        ObservedWorld.

        Parameters
        ----------
        result:
            Output of ReconciliationService.reconcile().
        observed:
            The same ObservedWorld that was passed to reconcile().
            ground_truth and corruption_events are accessed here ONLY.
        seed:
            Master seed used to generate this world.
        dataset_version / config_hash:
            Metadata from the generator config.
        throughput:
            Optional ThroughputResult from the benchmark harness.
        """
        now = datetime.now(tz=timezone.utc)

        ground_truth: list[GroundTruth] = observed.ground_truth
        corruption_events: list[CorruptionEvent] = observed.corruption_events

        # ------------------------------------------------------------------
        # Build lookup maps
        # ------------------------------------------------------------------
        gt_by_pid: dict[str, GroundTruth] = {gt.payment_id: gt for gt in ground_truth}
        decision_by_pid = {d.payment_id: d for d in result.decisions}
        card_by_pid = {c.payment_id: c for c in result.evidence_cards}

        # Map payment → settlement for batch integrity
        settlement_payment_map: dict[str, list[str]] = {}
        settlement_ref_map: dict[str, str] = {}
        for s in observed.settlements:
            settlement_payment_map[s.settlement_id] = list(s.payment_ids)
            for pid in s.payment_ids:
                settlement_ref_map[pid] = s.settlement_ref

        # Orphan entities injected (E008): corruption_events with orphan type
        orphan_injected_refs: set[str] = {
            ce.target_record_id
            for ce in corruption_events
            if ce.corruption_type == "orphan_bank_entry"
        }
        orphan_surfaced_ids: set[str] = {
            orp.entity_id for orp in result.orphan_records
            if orp.entity_type == "bank_entry"
        }

        # Fix B: build the COMPLETE set of legitimately-expected orphan entity IDs
        # from ALL corruption events, not only E008.
        # Centralised in exception_mapping.build_expected_orphan_entity_ids().
        expected_orphan_ids: set[str] = build_expected_orphan_entity_ids(
            corruption_events=corruption_events,
            observed_world=observed,
        )
        orphan_surfaced_ids: set[str] = {
            orp.entity_id for orp in result.orphan_records
            if orp.entity_type == "bank_entry"
        }

        # ------------------------------------------------------------------
        # Payment-level classification
        # ------------------------------------------------------------------
        entity_findings: list[EntityFinding] = []

        # Contamination checks (Model B)
        payments_in_observed_settlements = set()
        for s in observed.settlements:
            for pid in s.payment_ids:
                payments_in_observed_settlements.add(pid)

        contaminating_corruption_types = {
            "missing_bank_entry",
            "amount_mismatch",
            "date_mismatch",
            "duplicate_bank_entry",
            "settlement_fee_variance",
        }
        corrupted_pids = {
            ce.case_id for ce in corruption_events
            if ce.corruption_type in contaminating_corruption_types
        }

        contaminated_settlement_ids = set()
        for s in observed.settlements:
            if any(pid in corrupted_pids for pid in s.payment_ids):
                contaminated_settlement_ids.add(s.settlement_id)

        gt_decisions_post: dict[str, str] = {}

        tp = fp = tn = fn_clean = abst_clean = abst_corrupt = 0
        unsafe_by_corruption: dict[str, int] = {k: 0 for k in CORRUPTION_MAPPINGS}

        for pid, gt in gt_by_pid.items():
            engine_d = decision_by_pid.get(pid)
            engine_decision = engine_d.decision if engine_d else "MISSING"
            engine_codes = list(engine_d.exception_codes) if engine_d else []
            gt_decision = gt.expected_decision
            gen_type = gt.discrepancy_type  # None for clean
            gen_code = gt.discrepancy_code  # "E001"–"E008" or None

            # Propagate contamination for clean payments (Model B)
            if gen_type is None:
                # 1. Missing settlement (E001) contamination
                if pid not in payments_in_observed_settlements:
                    gt_decision = "ABSTAIN"
                    gen_type = "missing_settlement"
                    gen_code = None  # None for contaminated, not directly corrupted
                else:
                    # 2. Other shared evidence contamination
                    settlement = next((s for s in observed.settlements if pid in s.payment_ids), None)
                    if settlement and settlement.settlement_id in contaminated_settlement_ids:
                        gt_decision = "HUMAN_REVIEW"
                        # Find the corruption type that caused the contamination
                        batch_corruption_type = None
                        for b_pid in settlement.payment_ids:
                            if b_pid in corrupted_pids:
                                ce = next((c for c in corruption_events if c.case_id == b_pid), None)
                                if ce:
                                    batch_corruption_type = ce.corruption_type
                                    break
                        if batch_corruption_type:
                            gen_type = batch_corruption_type
                            gen_code = None  # None for contaminated, not directly corrupted

            gt_decisions_post[pid] = gt_decision
            expected_rec_codes = get_expected_rec_codes(gen_type) if gen_type else []

            # Classify payment outcome
            if gt_decision == "AUTO_MATCH":
                if engine_decision == "AUTO_MATCH":
                    outcome = "TP_MATCH"
                    tp += 1
                elif engine_decision == "ABSTAIN":
                    outcome = "ABST_CLEAN"
                    abst_clean += 1
                else:  # HUMAN_REVIEW or MISSING
                    outcome = "FN_MISS_CLEAN"
                    fn_clean += 1
            else:  # HUMAN_REVIEW expected (per ground truth)
                # ----------------------------------------------------------
                # Fix A — E008 payment-level special case.
                #
                # For orphan_bank_entry (E008), the ground truth generator
                # assigns HUMAN_REVIEW to the anchor case_id payment.
                # However, the anchor payment's own reconciliation chain is
                # UNAFFECTED by the orphan injection. The orphan has a
                # completely different settlement_ref and is resolved at the
                # entity level (in orphan_bank_entries).
                #
                # Therefore:
                #   engine AUTO_MATCH on E008 payment → TP_MATCH (correct)
                #   engine HUMAN_REVIEW on E008 payment → FN_MISS_CLEAN
                #     (over-conservative, but not a safety risk)
                #
                # Approved plan §4: "PAY_001 → AUTO_MATCH is CORRECT."
                # ----------------------------------------------------------
                if e008_payment_is_clean(gen_type) and engine_decision == "AUTO_MATCH":
                    outcome = "TP_MATCH"
                    tp += 1
                elif e008_payment_is_clean(gen_type) and engine_decision == "ABSTAIN":
                    # Over-conservative on a payment that should match
                    outcome = "ABST_CLEAN"
                    abst_clean += 1
                elif e008_payment_is_clean(gen_type):
                    # HUMAN_REVIEW on E008 anchor — over-conservative
                    outcome = "FN_MISS_CLEAN"
                    fn_clean += 1
                elif engine_decision == "AUTO_MATCH":
                    # All other HUMAN_REVIEW ground truth + engine AUTO_MATCH → FP_MATCH
                    outcome = "FP_MATCH"
                    fp += 1
                    if gen_type and gen_type in unsafe_by_corruption:
                        unsafe_by_corruption[gen_type] = unsafe_by_corruption.get(gen_type, 0) + 1
                elif engine_decision == "ABSTAIN":
                    outcome = "ABST_CORRUPT"
                    abst_corrupt += 1
                else:
                    outcome = "TN_EXCEPTION"
                    tn += 1

            # Exception code classification (for TN + ABST_CORRUPT)
            exc_class = "N_A"
            if outcome in ("TN_EXCEPTION", "ABST_CORRUPT") and gen_type:
                if not engine_codes:
                    exc_class = "NO_CODE"
                elif codes_intersect(engine_codes, gen_type):
                    exc_class = "CORRECT_CODE"
                else:
                    exc_class = "WRONG_CODE"
            elif outcome == "FP_MATCH":
                exc_class = "N_A"

            entity_findings.append(
                EntityFinding(
                    entity_type="payment",
                    record_id=pid,
                    payment_id=pid,
                    related_record_ids=_get_related_ids(pid, observed),
                    payment_outcome=outcome,
                    exception_classification=exc_class,
                    expected_outcome=gt_decision,
                    observed_outcome=engine_decision,
                    corruption_type=gen_type,
                    corruption_gen_code=gen_code,
                    expected_rec_codes=expected_rec_codes,
                    observed_rec_codes=engine_codes,
                    notes=gt.notes,
                )
            )

        # E008 directly-injected orphan entity findings
        orphan_detected_count = 0
        orphan_missed_count = 0
        false_orphan_count = 0

        for ce in corruption_events:
            if ce.corruption_type != "orphan_bank_entry":
                continue
            entity_id = ce.target_record_id
            if entity_id in orphan_surfaced_ids:
                orphan_detected_count += 1
                oo = "ORPHAN_DETECTED"
            else:
                orphan_missed_count += 1
                oo = "ORPHAN_MISSED"

            entity_findings.append(
                EntityFinding(
                    entity_type="bank_entry",
                    record_id=entity_id,
                    payment_id=None,  # orphan has no payment_id
                    related_record_ids=[ce.case_id],
                    orphan_outcome=oo,
                    expected_outcome="ORPHAN_DETECTED",
                    observed_outcome=oo,
                    corruption_type="orphan_bank_entry",
                    corruption_gen_code="E008",
                    expected_rec_codes=["rec:E008"],
                    observed_rec_codes=["rec:E008"] if oo == "ORPHAN_DETECTED" else [],
                )
            )

        # Fix B: FALSE_ORPHAN — only entities that the engine surfaces as
        # orphans AND that no corruption event legitimately explains.
        # Uses build_expected_orphan_entity_ids() which covers both direct
        # (E008) and indirect (E001-removed settlement → bank entry) cases.
        for orp in result.orphan_records:
            if orp.entity_id not in expected_orphan_ids:
                false_orphan_count += 1
                entity_findings.append(
                    EntityFinding(
                        entity_type="bank_entry",
                        record_id=orp.entity_id,
                        payment_id=None,
                        orphan_outcome="FALSE_ORPHAN",
                        expected_outcome="NOT_ORPHAN",
                        observed_outcome="ORPHAN_DETECTED",
                        observed_rec_codes=[orp.exception_code],
                        notes=(
                            f"Fix B: engine surfaced as orphan but no corruption event "
                            f"explains this. Notes: {orp.notes}"
                        ),
                    )
                )

        # ------------------------------------------------------------------
        # Reconciliation Scorecard (A)
        # ------------------------------------------------------------------
        n_total = len(gt_by_pid)
        # For recall purposes, count payments dynamically determined as clean AUTO_MATCH (Model B)
        n_clean = sum(
            1 for f in entity_findings
            if f.entity_type == "payment"
            and f.payment_outcome in ("TP_MATCH", "ABST_CLEAN", "FN_MISS_CLEAN")
        )
        # Effective corrupt count
        n_corrupt = n_total - n_clean
        n_am = sum(1 for d in result.decisions if d.decision == "AUTO_MATCH")
        n_hr = sum(1 for d in result.decisions if d.decision == "HUMAN_REVIEW")
        n_ab = sum(1 for d in result.decisions if d.decision == "ABSTAIN")

        prec, prec_i = compute_auto_match_precision(tp, fp)
        rec_, rec_i = compute_auto_match_recall(tp, n_clean)
        f1, f1_i = compute_reconciliation_f1(tp, fp, n_clean)

        recon_scorecard = ReconciliationScorecard(
            total_payments=n_total,
            clean_payments=n_clean,
            corrupted_payments=n_corrupt,
            auto_matched_count=n_am,
            human_review_count=n_hr,
            abstained_count=n_ab,
            correct_match_count=tp,
            incorrect_match_count=fp,
            missed_match_count=fn_clean,
            correct_exception_count=tn,
            false_exception_count=fn_clean,
            abstained_clean_count=abst_clean,
            abstained_corrupt_count=abst_corrupt,
            auto_match_precision=prec,
            auto_match_recall=rec_,
            reconciliation_f1=f1,
            resolution_rate=compute_resolution_rate(n_total, n_total),
            precision_insufficient_data=prec_i,
            recall_insufficient_data=rec_i,
            f1_insufficient_data=f1_i,
        )

        # ------------------------------------------------------------------
        # Unsafe auto-match metrics
        # ------------------------------------------------------------------
        unsafe_total = fp
        urate, urate_i = compute_unsafe_auto_match_rate(unsafe_total, n_am)
        unsafe_metrics = UnsafeAutoMatchMetrics(
            unsafe_auto_match_count=unsafe_total,
            total_auto_match_count=n_am,
            unsafe_auto_match_rate=urate,
            insufficient_data=urate_i,
            unsafe_auto_match_by_corruption=unsafe_by_corruption,
        )

        # ------------------------------------------------------------------
        # Exception Scorecard (B)
        # ------------------------------------------------------------------
        # Count code classification across TN + ABST_CORRUPT findings
        correct_code = sum(
            1 for f in entity_findings
            if f.entity_type == "payment"
            and f.exception_classification == "CORRECT_CODE"
        )
        wrong_code = sum(
            1 for f in entity_findings
            if f.entity_type == "payment"
            and f.exception_classification == "WRONG_CODE"
        )
        no_code = sum(
            1 for f in entity_findings
            if f.entity_type == "payment"
            and f.exception_classification == "NO_CODE"
        )

        # Total detected: TN + ABST_CORRUPT (payment) + orphan_detected
        correctly_detected = tn + abst_corrupt + orphan_detected_count
        missed_total = fp + orphan_missed_count    # fp = unsafe auto-match = missed exception
        false_detections = fn_clean + false_orphan_count

        # Total injected = corrupted payments (excluding E008 anchors) + injected orphan entities
        # E008 anchor payments are scored at entity level (orphan entity), not payment level.
        n_orphan_injected = sum(
            1 for ce in corruption_events if ce.corruption_type == "orphan_bank_entry"
        )
        # Corrupted payment count for exception scorecard excludes E008 anchors
        # (their exception is the orphan entity, not the payment itself)
        n_corrupt_payment_excep = n_corrupt  # already excludes E008 anchors via Fix A above
        total_injected = n_corrupt_payment_excep + n_orphan_injected

        ep, ep_i = compute_exception_precision(correctly_detected, false_detections)
        er, er_i = compute_exception_recall(correctly_detected, total_injected)
        ef, ef_i = compute_exception_f1(correctly_detected, false_detections, total_injected)

        exc_scorecard = ExceptionScorecard(
            total_injected_exceptions=total_injected,
            correctly_detected_exceptions=correctly_detected,
            missed_exceptions=missed_total,
            incorrectly_classified_exceptions=wrong_code,
            no_code_exceptions=no_code,
            false_exception_detections=false_detections,
            exception_detection_precision=ep,
            exception_detection_recall=er,
            exception_detection_f1=ef,
            precision_insufficient_data=ep_i,
            recall_insufficient_data=er_i,
            f1_insufficient_data=ef_i,
        )

        # ------------------------------------------------------------------
        # Per-corruption metrics
        # ------------------------------------------------------------------
        per_corruption = _build_per_corruption_metrics(entity_findings, corruption_events)

        # ------------------------------------------------------------------
        # Per-entity metrics
        # ------------------------------------------------------------------
        per_entity = _build_per_entity_metrics(entity_findings, observed, result)

        # ------------------------------------------------------------------
        # Batch integrity
        # ------------------------------------------------------------------
        batch_details, batch_scorecard = analyse_batch_integrity(
            result, settlement_payment_map, settlement_ref_map
        )

        # ------------------------------------------------------------------
        # Unresolved entities (for report)
        # ------------------------------------------------------------------
        unresolved = _build_unresolved(result, entity_findings, card_by_pid)

        # ------------------------------------------------------------------
        # Record counts / corruption profile
        # ------------------------------------------------------------------
        record_counts = {
            "merchants": len(observed.merchants),
            "payments": len(observed.payments),
            "settlements": len(observed.settlements),
            "bank_entries": len(observed.bank_entries),
            "ledger_entries": len(observed.ledger_entries),
            "ground_truth": len(ground_truth),
            "corruption_events": len(corruption_events),
        }
        corruption_profile: dict[str, int] = {}
        for ce in corruption_events:
            corruption_profile[ce.corruption_type] = corruption_profile.get(ce.corruption_type, 0) + 1
        clean_count = sum(1 for gt in ground_truth if gt.expected_decision == "AUTO_MATCH")
        corruption_profile["clean"] = clean_count

        entity_counts = {
            "total_payments": n_total,
            "clean_payments": n_clean,
            "clean_payments_gt": sum(1 for gt in ground_truth if gt.expected_decision == "AUTO_MATCH"),
            "e008_anchor_payments_reclassified": sum(
                1 for gt in ground_truth
                if gt.expected_decision == "HUMAN_REVIEW"
                and gt.discrepancy_type == "orphan_bank_entry"
            ),
            "corrupted_payments": n_corrupt,
            "total_orphan_entities_injected": n_orphan_injected,
            "total_duplicate_entities_injected": sum(
                1 for ce in corruption_events if ce.corruption_type == "duplicate_bank_entry"
            ),
        }

        return PerSeedResult(
            seed=seed,
            dataset_version=dataset_version,
            config_hash=config_hash,
            record_counts=record_counts,
            corruption_profile=corruption_profile,
            entity_counts=entity_counts,
            decision_distribution={
                "auto_matched": n_am,
                "human_review": n_hr,
                "abstained": n_ab,
            },
            reconciliation_scorecard=recon_scorecard,
            exception_scorecard=exc_scorecard,
            unsafe_auto_match_metrics=unsafe_metrics,
            batch_integrity_scorecard=batch_scorecard,
            per_corruption_metrics=per_corruption,
            per_entity_metrics=per_entity,
            batch_integrity_details=batch_details,
            entity_findings=entity_findings,
            unresolved_entities=unresolved,
            throughput=throughput,
            processed_at=now,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_related_ids(payment_id: str, observed: ObservedWorld) -> list[str]:
    """Return IDs of settlement, bank entry, and ledger entry related to this payment."""
    related = []
    for s in observed.settlements:
        if payment_id in s.payment_ids:
            related.append(s.settlement_id)
            for b in observed.bank_entries:
                if b.settlement_ref == s.settlement_ref:
                    related.append(b.bank_entry_id)
            break
    for le in observed.ledger_entries:
        if le.payment_id == payment_id:
            related.append(le.ledger_entry_id)
    return related


def _build_per_corruption_metrics(
    entity_findings: list[EntityFinding],
    corruption_events: list[CorruptionEvent],
) -> list[PerCorruptionMetric]:
    """Build one PerCorruptionMetric entry per generator E-code type."""
    metrics: list[PerCorruptionMetric] = []

    for gen_type, mapping in CORRUPTION_MAPPINGS.items():
        # Count injected for this type
        injected = sum(
            1 for ce in corruption_events if ce.corruption_type == gen_type
        )

        # Payment-level findings for this type
        pf = [
            f for f in entity_findings
            if f.entity_type == "payment"
            and f.corruption_type == gen_type
            and f.corruption_gen_code is not None
        ]

        # E008 orphan findings (entity_type == bank_entry)
        orphan_f = [
            f for f in entity_findings
            if f.entity_type == "bank_entry"
            and f.corruption_type == gen_type
            and f.orphan_outcome is not None
        ]

        # For E008, detection is via orphan_outcome
        if gen_type == "orphan_bank_entry":
            correctly_detected = sum(1 for f in orphan_f if f.orphan_outcome == "ORPHAN_DETECTED")
            missed = sum(1 for f in orphan_f if f.orphan_outcome == "ORPHAN_MISSED")
            fp_count = 0  # orphan payment itself may be TP_MATCH — counted there
            correct_code = correctly_detected  # presence in orphan_records implies rec:E008
            wrong_code = 0
            no_code = 0
        else:
            correctly_detected = sum(
                1 for f in pf if f.payment_outcome in ("TN_EXCEPTION", "ABST_CORRUPT")
            )
            missed = sum(1 for f in pf if f.payment_outcome == "FP_MATCH")
            fp_count = missed
            correct_code = sum(1 for f in pf if f.exception_classification == "CORRECT_CODE")
            wrong_code = sum(1 for f in pf if f.exception_classification == "WRONG_CODE")
            no_code = sum(1 for f in pf if f.exception_classification == "NO_CODE")

        dr, dr_i = compute_detection_rate(correctly_detected, injected)

        metrics.append(
            PerCorruptionMetric(
                corruption_type=gen_type,
                gen_code=mapping.gen_code,
                expected_rec_codes=list(mapping.expected_rec_codes),
                injected_count=injected,
                correctly_detected_count=correctly_detected,
                missed_count=missed,
                auto_matched_incorrectly_count=fp_count,
                correct_code_classification_count=correct_code,
                wrong_code_classification_count=wrong_code,
                no_code_count=no_code,
                detection_rate=dr,
                unsafe_auto_match_count=fp_count,
                insufficient_data=dr_i,
                notes=mapping.notes if fp_count > 0 or injected == 0 else "",
            )
        )

    return metrics


def _build_per_entity_metrics(
    entity_findings: list[EntityFinding],
    observed: ObservedWorld,
    result: BatchReconciliationResult,
) -> list[PerEntityMetric]:
    """Build per-entity-type summary metrics."""
    metrics: list[PerEntityMetric] = []

    # Payment-level
    pf = [f for f in entity_findings if f.entity_type == "payment"]
    corrupted_p = sum(1 for f in pf if f.corruption_type is not None)
    correctly_p = sum(1 for f in pf if f.payment_outcome in ("TN_EXCEPTION", "ABST_CORRUPT", "TP_MATCH"))
    incorrectly_p = sum(1 for f in pf if f.payment_outcome == "FP_MATCH")
    metrics.append(PerEntityMetric(
        entity_type="payment",
        total_observed=len(observed.payments),
        corrupted_count=corrupted_p,
        correctly_handled_count=correctly_p,
        incorrectly_handled_count=incorrectly_p,
        orphan_injected_count=0,
        orphan_detected_count=0,
        orphan_missed_count=0,
    ))

    # Bank entry level
    bf = [f for f in entity_findings if f.entity_type == "bank_entry"]
    orphan_injected = sum(1 for f in bf if f.orphan_outcome in ("ORPHAN_DETECTED", "ORPHAN_MISSED"))
    orphan_detected = sum(1 for f in bf if f.orphan_outcome == "ORPHAN_DETECTED")
    orphan_missed = sum(1 for f in bf if f.orphan_outcome == "ORPHAN_MISSED")
    # corrupted bank entries = payment findings with gen code E002/E004/E005/E006
    bank_corrupt_types = {"missing_bank_entry", "amount_mismatch", "date_mismatch", "duplicate_bank_entry"}
    corrupted_b = sum(1 for f in [f for f in entity_findings if f.entity_type == "payment"]
                      if f.corruption_type in bank_corrupt_types)
    correctly_b = sum(1 for f in [f for f in entity_findings if f.entity_type == "payment"]
                      if f.corruption_type in bank_corrupt_types
                      and f.payment_outcome in ("TN_EXCEPTION", "ABST_CORRUPT"))
    incorrectly_b = sum(1 for f in [f for f in entity_findings if f.entity_type == "payment"]
                        if f.corruption_type in bank_corrupt_types
                        and f.payment_outcome == "FP_MATCH")
    metrics.append(PerEntityMetric(
        entity_type="bank_entry",
        total_observed=len(observed.bank_entries),
        corrupted_count=corrupted_b,
        correctly_handled_count=correctly_b,
        incorrectly_handled_count=incorrectly_b,
        orphan_injected_count=orphan_injected,
        orphan_detected_count=orphan_detected,
        orphan_missed_count=orphan_missed,
    ))

    # Settlement level
    settlement_corrupt_types = {"missing_settlement", "settlement_fee_variance"}
    corrupted_s = sum(1 for f in [f for f in entity_findings if f.entity_type == "payment"]
                      if f.corruption_type in settlement_corrupt_types)
    correctly_s = sum(1 for f in [f for f in entity_findings if f.entity_type == "payment"]
                      if f.corruption_type in settlement_corrupt_types
                      and f.payment_outcome in ("TN_EXCEPTION", "ABST_CORRUPT", "ABSTAIN"))
    incorrectly_s = sum(1 for f in [f for f in entity_findings if f.entity_type == "payment"]
                        if f.corruption_type in settlement_corrupt_types
                        and f.payment_outcome == "FP_MATCH")
    metrics.append(PerEntityMetric(
        entity_type="settlement",
        total_observed=len(observed.settlements),
        corrupted_count=corrupted_s,
        correctly_handled_count=correctly_s,
        incorrectly_handled_count=incorrectly_s,
        orphan_injected_count=0,
        orphan_detected_count=0,
        orphan_missed_count=0,
    ))

    # Ledger entry level
    ledger_corrupt_types = {"missing_ledger_entry"}
    corrupted_l = sum(1 for f in [f for f in entity_findings if f.entity_type == "payment"]
                      if f.corruption_type in ledger_corrupt_types)
    correctly_l = sum(1 for f in [f for f in entity_findings if f.entity_type == "payment"]
                      if f.corruption_type in ledger_corrupt_types
                      and f.payment_outcome in ("TN_EXCEPTION", "ABST_CORRUPT"))
    incorrectly_l = sum(1 for f in [f for f in entity_findings if f.entity_type == "payment"]
                        if f.corruption_type in ledger_corrupt_types
                        and f.payment_outcome == "FP_MATCH")
    metrics.append(PerEntityMetric(
        entity_type="ledger_entry",
        total_observed=len(observed.ledger_entries),
        corrupted_count=corrupted_l,
        correctly_handled_count=correctly_l,
        incorrectly_handled_count=incorrectly_l,
        orphan_injected_count=0,
        orphan_detected_count=0,
        orphan_missed_count=0,
    ))

    return metrics


def _build_unresolved(
    result: BatchReconciliationResult,
    entity_findings: list[EntityFinding],
    card_by_pid: dict,
) -> list[dict]:
    """Build the unresolved_entities list for the output report."""
    unresolved = []

    # Payment-level unresolved
    for f in entity_findings:
        if f.entity_type != "payment":
            continue
        if f.payment_outcome in ("TN_EXCEPTION", "ABST_CORRUPT", "FN_MISS_CLEAN", "ABST_CLEAN"):
            card = card_by_pid.get(f.record_id)
            unresolved.append({
                "entity_type": "payment",
                "record_id": f.record_id,
                "payment_id": f.record_id,
                "related_record_ids": f.related_record_ids,
                "engine_decision": f.observed_outcome,
                "engine_confidence": (
                    str(card.confidence) if card else None
                ),
                "engine_exception_codes": f.observed_rec_codes,
                "stage_reached": card.stage_reached if card else None,
                "notes": card.notes if card else "",
            })

    # Orphan bank entries
    for orp in result.orphan_records:
        unresolved.append({
            "entity_type": orp.entity_type,
            "record_id": orp.entity_id,
            "payment_id": None,
            "related_record_ids": [],
            "engine_decision": "ORPHAN",
            "engine_confidence": None,
            "engine_exception_codes": [orp.exception_code],
            "stage_reached": "normaliser",
            "notes": orp.notes,
        })

    return unresolved
