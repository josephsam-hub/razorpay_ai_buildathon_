"""
LedgerLens Phase 3.2 — Throughput Benchmark Harness
=====================================================
Measures reconciliation throughput for various dataset sizes.

RULES:
  - Only the reconcile() call is timed — generation is timed separately.
  - The production ReconciliationService has no timing instrumentation.
  - P95 latency requires per-record instrumentation available in benchmark mode only.
  - Results are never cached between runs; each run generates fresh data.
  - Seed 999 (holdout) must never be benchmarked outside the final demo.

USAGE:
  from app.core.evaluation.benchmark import BenchmarkHarness
  harness = BenchmarkHarness()
  result = harness.run(config, runs=3, measure_p95=False)
"""

from __future__ import annotations

import sys
import time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from app.data.generator.config import DatasetConfig, load_config
from app.data.generator.world import generate
from app.models.evaluation import ThroughputResult
from app.services.reconciliation import ReconciliationService

_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


class BenchmarkHarness:
    """
    Benchmark the reconciliation engine for a given dataset config.
    Not intended for production use — benchmark mode only.
    """

    def __init__(self) -> None:
        self._service = ReconciliationService()

    def run(
        self,
        config: DatasetConfig,
        runs: int = 3,
        measure_p95: bool = False,
    ) -> ThroughputResult:
        """
        Run the reconciliation engine `runs` times and report mean throughput.

        Parameters
        ----------
        config:
            DatasetConfig to generate and reconcile.
        runs:
            Number of independent runs to average.
        measure_p95:
            If True, wraps per-record timing (adds overhead — benchmark mode only).

        Returns
        -------
        ThroughputResult with mean wall_clock_seconds, records_per_second,
        avg_latency_ms, and optionally p95_latency_ms.
        """
        wall_times: list[float] = []
        p95_values: list[float] = []
        n_records: int = config.n_payments

        for _ in range(runs):
            # Generate fresh data for each run (no caching)
            _clean, observed = generate(config)

            if measure_p95:
                wall_s, p95_ms = self._run_timed_with_p95(observed)
                p95_values.append(p95_ms)
            else:
                wall_s = self._run_timed(observed)

            wall_times.append(wall_s)

        mean_wall = sum(wall_times) / len(wall_times)
        mean_wall_dec = Decimal(str(mean_wall)).quantize(_FOUR, rounding=ROUND_HALF_UP)

        rps = Decimal(n_records) / mean_wall_dec if mean_wall_dec > 0 else Decimal("0")
        rps = rps.quantize(_TWO, rounding=ROUND_HALF_UP)

        avg_lat = (mean_wall_dec * Decimal("1000") / Decimal(n_records)
                   if n_records > 0 else Decimal("0"))
        avg_lat = avg_lat.quantize(_FOUR, rounding=ROUND_HALF_UP)

        p95_dec: Decimal | None = None
        if measure_p95 and p95_values:
            p95_dec = Decimal(str(sum(p95_values) / len(p95_values))).quantize(
                _FOUR, rounding=ROUND_HALF_UP
            )

        return ThroughputResult(
            total_records=n_records,
            wall_clock_seconds=mean_wall_dec,
            records_per_second=rps,
            avg_latency_ms=avg_lat,
            p95_latency_ms=p95_dec,
            benchmark_mode=True,
            platform=sys.platform,
            python_version=(
                f"{sys.version_info.major}."
                f"{sys.version_info.minor}."
                f"{sys.version_info.micro}"
            ),
            runs_averaged=runs,
        )

    def run_from_config_file(
        self,
        config_path: Path,
        runs: int = 3,
        measure_p95: bool = False,
    ) -> ThroughputResult:
        config = load_config(config_path)
        return self.run(config, runs=runs, measure_p95=measure_p95)

    # ------------------------------------------------------------------
    # Internal timing helpers
    # ------------------------------------------------------------------

    def _run_timed(self, observed) -> float:
        """Run reconciliation once and return wall-clock seconds."""
        t0 = time.perf_counter()
        self._service.reconcile(observed)
        return time.perf_counter() - t0

    def _run_timed_with_p95(self, observed) -> tuple[float, float]:
        """
        Run reconciliation with per-record timing.
        Returns (total_seconds, p95_latency_ms).

        This bypasses the service facade and calls the engine internals
        directly so we can time each payment individually.
        """
        from app.core.reconciliation.normaliser import normalise
        from app.core.reconciliation.engine import reconcile_from_normaliser

        t_total_start = time.perf_counter()

        norm_result = normalise(observed)
        per_record_ms: list[float] = []

        # Time each payment individually via the normaliser output
        # We reconstruct the batch one record at a time
        for ct in norm_result.canonical_transactions:
            from app.core.reconciliation.normaliser import NormaliserResult
            single = NormaliserResult(canonical_transactions=[ct])
            t0 = time.perf_counter()
            reconcile_from_normaliser(single, batch_id="_bench")
            per_record_ms.append((time.perf_counter() - t0) * 1000)

        total_s = time.perf_counter() - t_total_start

        if per_record_ms:
            sorted_ms = sorted(per_record_ms)
            p95_idx = int(len(sorted_ms) * 0.95)
            p95_ms = sorted_ms[min(p95_idx, len(sorted_ms) - 1)]
        else:
            p95_ms = 0.0

        return total_s, p95_ms
