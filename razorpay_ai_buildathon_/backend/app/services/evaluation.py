"""
LedgerLens Phase 3.2 — EvaluationService
==========================================
Public facade for the Phase 3.2 evaluation layer.

Usage (single seed):
    service = EvaluationService()
    result = service.evaluate_seed(config, seed=100)
    print(result.reconciliation_scorecard.auto_match_precision)

Usage (multi-seed):
    report = service.evaluate_multi_seed(config, seeds=[100,101,102])

GROUND-TRUTH ISOLATION:
  The reconciliation engine (ReconciliationService) is called first.
  Ground truth is accessed only inside the Evaluator — never by the engine.

HOLDOUT GUARD:
  This service calls assert_not_holdout() for every seed by default.
  Pass allow_holdout=True only for the final demo run.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from app.data.generator.config import DatasetConfig
from app.data.generator.world import generate
from app.models.evaluation import AggregateEvaluationReport, PerSeedResult
from app.core.evaluation.evaluator import Evaluator
from app.core.evaluation.aggregator import MultiSeedAggregator
from app.core.evaluation.benchmark import BenchmarkHarness
from app.core.evaluation.exception_mapping import assert_not_holdout, classify_seed
from app.services.reconciliation import ReconciliationService


class EvaluationService:
    """
    Stateless evaluation service.

    Orchestrates: generate → reconcile → evaluate → (optionally) aggregate.
    Ground truth never crosses into the reconciliation layer.
    """

    def __init__(self) -> None:
        self._recon = ReconciliationService()
        self._evaluator = Evaluator()
        self._aggregator = MultiSeedAggregator()
        self._bench = BenchmarkHarness()

    def evaluate_seed(
        self,
        config: DatasetConfig,
        seed: int | None = None,
        allow_holdout: bool = False,
        include_throughput: bool = False,
    ) -> PerSeedResult:
        """
        Generate, reconcile, and evaluate one dataset.

        Parameters
        ----------
        config:
            DatasetConfig. seed field used unless override provided.
        seed:
            Override seed (replaces config.seed for this run).
        allow_holdout:
            Set True ONLY for the final demo. Guards against accidental
            holdout use during development.
        include_throughput:
            If True, runs a single-pass throughput measurement and
            attaches the result to PerSeedResult.throughput.
        """
        effective_seed = seed if seed is not None else config.seed

        if not allow_holdout:
            assert_not_holdout(effective_seed)

        # Rebuild config with the effective seed if it differs
        if effective_seed != config.seed:
            config = config.model_copy(update={"seed": effective_seed})

        # Step 1: Generate
        _clean, observed = generate(config)

        # Step 2: Reconcile (engine NEVER sees ground_truth / corruption_events)
        result, _exceptions = self._recon.reconcile(observed)

        # Step 3: Optionally measure throughput (single pass, no p95)
        throughput = None
        if include_throughput:
            throughput = self._bench.run(config, runs=1, measure_p95=False)

        # Step 4: Evaluate (ground truth accessed HERE only)
        per_seed = self._evaluator.evaluate(
            result=result,
            observed=observed,
            seed=effective_seed,
            dataset_version=config.version,
            config_hash="",  # caller can supply hash_config_file() if needed
            throughput=throughput,
        )

        return per_seed

    def evaluate_multi_seed(
        self,
        config: DatasetConfig,
        seeds: list[int],
        run_id: str | None = None,
        allow_holdout: bool = False,
        include_throughput: bool = False,
    ) -> AggregateEvaluationReport:
        """
        Evaluate across multiple seeds and aggregate results.

        Parameters
        ----------
        config:
            Base config. Seed is overridden per run.
        seeds:
            List of seeds. Must be unique. Seed 999 blocked unless allow_holdout=True.
        run_id:
            Stable identifier for this aggregate run. Auto-generated if None.
        allow_holdout:
            Must be True to use seed 999.
        """
        if run_id is None:
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
            run_id = f"EVAL_{ts}"

        per_seed_results: list[PerSeedResult] = []
        for s in seeds:
            psr = self.evaluate_seed(
                config, seed=s,
                allow_holdout=allow_holdout,
                include_throughput=include_throughput,
            )
            per_seed_results.append(psr)

        # Infer partition from first seed
        partition = classify_seed(seeds[0]) if seeds else "evaluation"
        if partition == "unknown":
            partition = "evaluation"

        return self._aggregator.aggregate(
            per_seed_results,
            run_id=run_id,
            partition=partition,
            engine_commit="",
        )
