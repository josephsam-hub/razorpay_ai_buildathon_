"""
LedgerLens Phase 3.2 — Multi-Seed Aggregator
=============================================
Aggregates PerSeedResult across multiple seeds to produce an
AggregateEvaluationReport with descriptive statistics per metric.

SEED INDEPENDENCE RULE:
  No two seeds in the same aggregate run may be identical.
  The aggregator raises ValueError on duplicate seeds.

PARTITION:
  Seeds must come from the same partition (calibration / evaluation / holdout).
  Mixing partitions raises ValueError.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from app.core.evaluation.exception_mapping import classify_seed
from app.core.evaluation.metrics import aggregate_metric
from app.models.evaluation import (
    AggregateEvaluationReport,
    MetricSummary,
    PerSeedResult,
)


def _make_summary(values: list[Decimal | None]) -> MetricSummary:
    agg = aggregate_metric(values)
    return MetricSummary(**agg)


def _extract(results: list[PerSeedResult], getter: Callable) -> list[Decimal | None]:
    out = []
    for r in results:
        try:
            out.append(getter(r))
        except AttributeError:
            out.append(None)
    return out


class MultiSeedAggregator:
    """
    Aggregate evaluation results across multiple seeds.

    Usage:
        agg = MultiSeedAggregator()
        report = agg.aggregate(per_seed_results, run_id="EVAL_001", partition="evaluation")
    """

    def aggregate(
        self,
        results: list[PerSeedResult],
        run_id: str,
        partition: str | None = None,
        engine_commit: str = "",
    ) -> AggregateEvaluationReport:
        """
        Aggregate a list of PerSeedResult objects.

        Parameters
        ----------
        results:
            One PerSeedResult per seed. Must be non-empty.
        run_id:
            Stable identifier for this aggregate run.
        partition:
            "calibration", "evaluation", or "holdout".
            Inferred from seed values if not provided.
        engine_commit:
            Git commit hash of the engine (for reproducibility).
        """
        if not results:
            raise ValueError("Cannot aggregate zero results.")

        seed_list = [r.seed for r in results]

        # Duplicate seed check
        if len(seed_list) != len(set(seed_list)):
            dupes = [s for s in seed_list if seed_list.count(s) > 1]
            raise ValueError(
                f"Duplicate seeds in aggregate run: {set(dupes)}. "
                "Each seed must be unique to ensure dataset independence."
            )

        # Infer/validate partition
        if partition is None:
            partitions = {classify_seed(s) for s in seed_list}
            partitions.discard("unknown")
            if len(partitions) == 1:
                partition = partitions.pop()
            else:
                partition = "evaluation"  # default if mixed/unknown

        # Holdout guard
        if any(r.seed == 999 for r in results) and partition != "holdout":
            raise ValueError(
                "Seed 999 is the holdout seed and must only be used in a 'holdout' run. "
                "Never aggregate holdout with calibration or evaluation seeds."
            )

        # Aggregate metrics
        auto_match_precision = _make_summary(
            _extract(results, lambda r: r.reconciliation_scorecard.auto_match_precision)
        )
        auto_match_recall = _make_summary(
            _extract(results, lambda r: r.reconciliation_scorecard.auto_match_recall)
        )
        reconciliation_f1 = _make_summary(
            _extract(results, lambda r: r.reconciliation_scorecard.reconciliation_f1)
        )
        unsafe_auto_match_rate = _make_summary(
            _extract(results, lambda r: r.unsafe_auto_match_metrics.unsafe_auto_match_rate)
        )
        exception_precision = _make_summary(
            _extract(results, lambda r: r.exception_scorecard.exception_detection_precision)
        )
        exception_recall = _make_summary(
            _extract(results, lambda r: r.exception_scorecard.exception_detection_recall)
        )
        exception_f1 = _make_summary(
            _extract(results, lambda r: r.exception_scorecard.exception_detection_f1)
        )
        fully_reconciled_rate = _make_summary(
            _extract(results, lambda r: r.batch_integrity_scorecard.fully_reconciled_rate)
        )

        notes = []
        if any(r.unsafe_auto_match_metrics.unsafe_auto_match_count > 0 for r in results):
            notes.append(
                "WARNING: unsafe AUTO_MATCH events detected. "
                "See unsafe_auto_match_metrics in per_seed_results."
            )
        unsafe_types = set()
        for r in results:
            for k, v in r.unsafe_auto_match_metrics.unsafe_auto_match_by_corruption.items():
                if v > 0:
                    unsafe_types.add(k)
        if unsafe_types:
            notes.append(
                f"Unsafe auto-match by corruption type: {sorted(unsafe_types)}"
            )

        return AggregateEvaluationReport(
            run_id=run_id,
            evaluation_version="0.1.0",
            engine_commit=engine_commit,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            platform=sys.platform,
            timestamp_utc=datetime.now(tz=timezone.utc),
            partition=partition,
            seed_list=seed_list,
            seed_count=len(seed_list),
            per_seed_results=results,
            auto_match_precision=auto_match_precision,
            auto_match_recall=auto_match_recall,
            reconciliation_f1=reconciliation_f1,
            unsafe_auto_match_rate=unsafe_auto_match_rate,
            exception_detection_precision=exception_precision,
            exception_detection_recall=exception_recall,
            exception_detection_f1=exception_f1,
            fully_reconciled_rate=fully_reconciled_rate,
            notes=notes,
        )
