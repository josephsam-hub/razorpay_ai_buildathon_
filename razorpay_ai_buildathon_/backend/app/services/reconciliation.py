"""
LedgerLens Phase 3 — ReconciliationService
============================================
Public facade for the Phase 3.1 in-memory reconciliation engine.

Usage:
    service = ReconciliationService()
    result, exceptions = service.reconcile(observed_world)

The service is stateless and pure. Every call is independent.
It never mutates the ObservedWorld or any of its contained entities.

PIPELINE:
  1. normalise(observed_world)          → NormaliserResult
     (includes canonical_transactions, duplicates, orphans)
  2. reconcile_from_normaliser(result)  → BatchReconciliationResult + list[ExceptionRecord]

Fix 2/4: The NormaliserResult carries duplicate and orphan records.
The engine surfaces them as rec:E003 (duplicate) and OrphanRecord entries.
No financial record is silently discarded.

DETERMINISM:
  Given identical ObservedWorld input, reconcile() always produces logically
  identical output (same decisions, same confidence values, same evidence).
  The processed_at timestamp in EvidenceCard / BatchReconciliationResult is
  generated once per call and does not affect any matching or scoring logic.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.data.generator.world import ObservedWorld
from app.models.decisions import BatchReconciliationResult
from app.models.exceptions import ExceptionRecord
from app.core.reconciliation.normaliser import normalise
from app.core.reconciliation.engine import reconcile_from_normaliser


class ReconciliationService:
    """
    Stateless in-memory reconciliation service.

    Phase 3.1 scope: pure in-memory processing.
    No database, no persistence, no external calls.
    """

    def reconcile(
        self,
        observed: ObservedWorld,
        batch_id: str | None = None,
        now: datetime | None = None,
    ) -> tuple[BatchReconciliationResult, list[ExceptionRecord]]:
        """
        Reconcile all payments in the ObservedWorld.

        Parameters
        ----------
        observed:
            The ObservedWorld produced by the Phase 2 generator.
            Must NOT rely on GroundTruth or CorruptionEvent — those are
            evaluator-only fields on ObservedWorld and are ignored here.
        batch_id:
            Optional stable identifier for this batch. Defaults to a
            deterministic ID derived from the first payment date and
            payment count.
        now:
            Optional UTC timestamp for audit fields. Defaults to
            datetime.now(tz=timezone.utc). Never affects matching logic.

        Returns
        -------
        (BatchReconciliationResult, list[ExceptionRecord])
            BatchReconciliationResult.orphan_records contains Fix 4 orphans.
        """
        if now is None:
            now = datetime.now(tz=timezone.utc)

        if batch_id is None:
            if observed.payments:
                first_date = min(p.payment_date for p in observed.payments)
                batch_id = (
                    f"BATCH_{first_date.strftime('%Y%m%d')}_{len(observed.payments):04d}"
                )
            else:
                batch_id = "BATCH_EMPTY"

        # Step 1 — Normalise (returns duplicates and orphans too)
        norm_result = normalise(observed)

        # Step 2 — Reconcile with full duplicate/orphan awareness
        result, exceptions = reconcile_from_normaliser(
            norm_result=norm_result,
            batch_id=batch_id,
            now=now,
        )

        return result, exceptions
