#!/usr/bin/env python3
"""
LedgerLens — Benchmark and Evaluation Runner CLI
================================================
Entry point for executing deterministic reconciliation benchmarks,
evaluating match precision and recall, and measuring performance throughput.

Usage:
  python scripts/run_benchmark.py --config data/synthetic/config_bench_100.yaml --seed 42
  python scripts/run_benchmark.py --config data/synthetic/config_bench_100.yaml --seeds 100,101,102
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Resolve path to backend to enable app.* imports
REPO_ROOT = Path(__file__).parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from app.data.generator.config import load_config
    from app.services.evaluation import EvaluationService
    from app.core.evaluation.benchmark import BenchmarkHarness
    from app.core.evaluation.aggregator import MultiSeedAggregator
    from app.core.evaluation.exception_mapping import classify_seed
except ImportError as e:
    print(f"ERROR: Failed to import backend modules: {e}", file=sys.stderr)
    print("Ensure you run this script from the repository root.", file=sys.stderr)
    sys.exit(1)


def parse_seeds(seed_str: str) -> list[int]:
    """Parse comma-separated seed integers, returning a unique list or raising ValueError."""
    seeds: list[int] = []
    for part in seed_str.split(","):
        part_str = part.strip()
        if not part_str:
            raise ValueError("Empty seed value in seeds list.")
        try:
            val = int(part_str)
        except ValueError:
            raise ValueError(f"Invalid integer seed value: '{part_str}'")
        seeds.append(val)

    if len(seeds) != len(set(seeds)):
        raise ValueError("Duplicate seeds detected in seeds list.")

    return seeds


def print_single_report(psr) -> None:
    """Print a clean structured report for a single seed evaluation run."""
    recon = psr.reconciliation_scorecard
    tp = psr.throughput

    # Calculate match rate: auto_matched / total
    match_rate = None
    if recon.total_payments > 0:
        match_rate = (recon.auto_matched_count / recon.total_payments) * 100

    print("================================================================================")
    print(f" LEDGERLENS BENCHMARK REPORT — SEED {psr.seed}")
    print("================================================================================")
    print(f"Config Version:     {psr.dataset_version}")
    print(f"Processed At:       {psr.processed_at}")
    print(f"Record Count:       {psr.record_counts.get('payments', recon.total_payments)} payments")
    print(f"Decision Split:     Auto-Matched={recon.auto_matched_count}, Human-Review={recon.human_review_count}, Abstained={recon.abstained_count}")
    print("--------------------------------------------------------------------------------")
    print(" RECONCILIATION ACCURACY METRICS")
    print("--------------------------------------------------------------------------------")
    print(f"  Precision:        {recon.auto_match_precision if recon.auto_match_precision is not None else 'N/A'}")
    print(f"  Recall:           {recon.auto_match_recall if recon.auto_match_recall is not None else 'N/A'}")
    print(f"  F1-Score:         {recon.reconciliation_f1 if recon.reconciliation_f1 is not None else 'N/A'}")
    print(f"  Resolution Rate:  {recon.resolution_rate:.4f}")
    if match_rate is not None:
        print(f"  Auto-Match Rate:  {match_rate:.2f}%")
    print("--------------------------------------------------------------------------------")
    print(" PERFORMANCE THROUGHPUT METRICS")
    print("--------------------------------------------------------------------------------")
    if tp:
        print(f"  Wall-Clock Time:  {tp.wall_clock_seconds:.4f} seconds")
        print(f"  Throughput:       {tp.records_per_second:.2f} payments/sec")
        print(f"  Avg Latency:      {tp.avg_latency_ms:.4f} ms/payment")
        print(f"  P95 Latency:      {tp.p95_latency_ms if tp.p95_latency_ms is not None else 'N/A'} ms/payment")
        print(f"  Runs Averaged:    {tp.runs_averaged}")
    else:
        print("  Throughput data not measured.")
    print("================================================================================")


def print_aggregate_report(report) -> None:
    """Print aggregated statistics summary across multiple seeds."""
    print("================================================================================")
    print(f" LEDGERLENS MULTI-SEED AGGREGATE BENCHMARK REPORT")
    print("================================================================================")
    print(f"Run ID:             {report.run_id}")
    print(f"Timestamp UTC:      {report.timestamp_utc}")
    print(f"Partition:          {report.partition.upper()}")
    print(f"Seed List:          {', '.join(map(str, report.seed_list))} (Count: {report.seed_count})")
    print("--------------------------------------------------------------------------------")
    print(" AGGREGATE RECONCILIATION ACCURACY METRICS (Mean | Min | Max)")
    print("--------------------------------------------------------------------------------")

    def fmt_stat(summary):
        if summary.mean is None:
            return "N/A"
        return f"{summary.mean:.4f}  (Min: {summary.min:.4f} | Max: {summary.max:.4f})"

    print(f"  Auto-Match Precision:  {fmt_stat(report.auto_match_precision)}")
    print(f"  Auto-Match Recall:     {fmt_stat(report.auto_match_recall)}")
    print(f"  Reconciliation F1:     {fmt_stat(report.reconciliation_f1)}")
    print(f"  Unsafe Auto-Match Rate: {fmt_stat(report.unsafe_auto_match_rate)}")
    print(f"  Fully Reconciled Rate: {fmt_stat(report.fully_reconciled_rate)}")

    print("--------------------------------------------------------------------------------")
    print(" AGGREGATE EXCEPTION DETECTION METRICS (Mean | Min | Max)")
    print("--------------------------------------------------------------------------------")
    print(f"  Exception Precision:   {fmt_stat(report.exception_detection_precision)}")
    print(f"  Exception Recall:      {fmt_stat(report.exception_detection_recall)}")
    print(f"  Exception F1:          {fmt_stat(report.exception_detection_f1)}")

    # Aggregate Throughput manually from results (aggregator does not aggregate throughput objects)
    print("--------------------------------------------------------------------------------")
    print(" AGGREGATE PERFORMANCE THROUGHPUT METRICS")
    print("--------------------------------------------------------------------------------")
    tps = [r.throughput for r in report.per_seed_results if r.throughput]
    if tps:
        rpss = [tp.records_per_second for tp in tps]
        avg_lats = [tp.avg_latency_ms for tp in tps]
        mean_rps = sum(rpss) / len(rpss)
        min_rps = min(rpss)
        max_rps = max(rpss)
        mean_lat = sum(avg_lats) / len(avg_lats)

        print(f"  Throughput (rps):      {mean_rps:.2f}  (Min: {min_rps:.2f} | Max: {max_rps:.2f})")
        print(f"  Avg Latency (ms):      {mean_lat:.4f} ms/payment")
    else:
        print("  Throughput data not measured.")

    if report.notes:
        print("--------------------------------------------------------------------------------")
        print(" NOTES / WARNINGS")
        print("--------------------------------------------------------------------------------")
        for note in report.notes:
            print(f"  * {note}")

    print("================================================================================")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ledgerlens-benchmark",
        description="LedgerLens — Reconciliation Benchmark & Accuracy Evaluator CLI",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to YAML benchmark configuration file",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--seed",
        type=int,
        help="Single seed configuration override",
    )
    group.add_argument(
        "--seeds",
        type=str,
        help="Comma-separated list of multiple unique seeds to execute and aggregate",
    )

    args = parser.parse_args(argv)

    config_path: Path = args.config
    if not config_path.exists():
        print(f"ERROR: Configuration file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"ERROR: Failed to load config file: {e}", file=sys.stderr)
        return 1

    # Extract target seeds
    target_seeds: list[int] = []
    is_multi = False

    if args.seed is not None:
        target_seeds = [args.seed]
    elif args.seeds is not None:
        is_multi = True
        try:
            target_seeds = parse_seeds(args.seeds)
        except ValueError as e:
            print(f"ERROR: Malformed seeds parameter: {e}", file=sys.stderr)
            return 1
    else:
        # Fall back to seed in the config file
        target_seeds = [config.seed]

    # Holdout seed protection validation
    for s in target_seeds:
        if s == 999:
            print("ERROR: Seed 999 is the holdout seed and is strictly forbidden.", file=sys.stderr)
            return 1

    # Run execution
    try:
        eval_service = EvaluationService()
        bench_harness = BenchmarkHarness()

        per_seed_results = []
        for s in target_seeds:
            # 1. Run accuracy evaluator
            psr = eval_service.evaluate_seed(
                config, seed=s,
                allow_holdout=False,
                include_throughput=False,
            )
            # 2. Run throughput harness (3 runs, measure p95)
            # Rebuild config for harness targeting the correct seed
            config_harness = config.model_copy(update={"seed": s})
            tp_res = bench_harness.run(config_harness, runs=3, measure_p95=True)

            # Attach performance measurements via copy
            psr_with_tp = psr.model_copy(update={"throughput": tp_res})
            per_seed_results.append(psr_with_tp)

        if not is_multi:
            # Single-seed print
            print_single_report(per_seed_results[0])
        else:
            # Multi-seed aggregate print
            aggregator = MultiSeedAggregator()
            partition = classify_seed(target_seeds[0])
            if partition == "unknown":
                partition = "evaluation"

            report = aggregator.aggregate(
                per_seed_results,
                run_id="CLI_BENCHMARK_RUN",
                partition=partition,
            )
            print_aggregate_report(report)

    except Exception as e:
        print(f"ERROR: Benchmark execution failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
