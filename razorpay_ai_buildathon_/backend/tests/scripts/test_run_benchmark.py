from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add repository root to sys.path so we can import the scripts package
REPO_ROOT = Path(__file__).parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_benchmark import main, parse_seeds


@pytest.fixture
def dummy_config_path(tmp_path):
    """Create a temporary valid minimal benchmark configuration file."""
    config_file = tmp_path / "config_bench_100.yaml"
    config_file.write_text("""
version: '1.0'
n_payments: 100
n_merchants: 3
seed: 42
start_date: '2026-08-01'
end_date: '2026-08-31'
""", encoding="utf-8")
    return config_file


def test_parse_seeds_valid():
    assert parse_seeds("100, 101, 102") == [100, 101, 102]
    assert parse_seeds("42") == [42]


def test_parse_seeds_malformed():
    with pytest.raises(ValueError, match="Empty seed value"):
        parse_seeds("100,,102")
    with pytest.raises(ValueError, match="Invalid integer"):
        parse_seeds("100, abc, 102")


def test_parse_seeds_duplicates():
    with pytest.raises(ValueError, match="Duplicate seeds"):
        parse_seeds("100, 101, 100")


def test_reject_both_seed_and_seeds(dummy_config_path):
    with pytest.raises(SystemExit):
        main(["--config", str(dummy_config_path), "--seed", "42", "--seeds", "100,101"])


def test_reject_holdout_seed_999(dummy_config_path):
    # Single seed holdout check
    code = main(["--config", str(dummy_config_path), "--seed", "999"])
    assert code != 0

    # Multi-seed list holdout check
    code = main(["--config", str(dummy_config_path), "--seeds", "100,999,101"])
    assert code != 0


def test_reject_duplicate_seeds(dummy_config_path):
    code = main(["--config", str(dummy_config_path), "--seeds", "100,101,100"])
    assert code != 0


def test_reject_malformed_seeds_arg(dummy_config_path):
    code = main(["--config", str(dummy_config_path), "--seeds", "100,abc,101"])
    assert code != 0


@patch("scripts.run_benchmark.EvaluationService")
@patch("scripts.run_benchmark.BenchmarkHarness")
def test_successful_single_seed_mocked(mock_harness_cls, mock_service_cls, dummy_config_path):
    mock_service = mock_service_cls.return_value
    mock_harness = mock_harness_cls.return_value

    from app.models.evaluation import (
        PerSeedResult,
        ReconciliationScorecard,
        ThroughputResult,
        ExceptionScorecard,
        UnsafeAutoMatchMetrics,
        BatchIntegrityScorecard,
    )

    recon_score = ReconciliationScorecard(
        total_payments=100,
        clean_payments=80,
        corrupted_payments=20,
        auto_matched_count=80,
        human_review_count=15,
        abstained_count=5,
        correct_match_count=78,
        incorrect_match_count=2,
        missed_match_count=2,
        correct_exception_count=18,
        false_exception_count=2,
        abstained_clean_count=0,
        abstained_corrupt_count=5,
        auto_match_precision=Decimal("0.9750"),
        auto_match_recall=Decimal("0.9750"),
        reconciliation_f1=Decimal("0.9750"),
        resolution_rate=Decimal("1.0"),
    )

    exc_score = ExceptionScorecard(
        total_injected_exceptions=20,
        correctly_detected_exceptions=18,
        missed_exceptions=2,
        incorrectly_classified_exceptions=0,
        no_code_exceptions=0,
        false_exception_detections=2,
        exception_detection_precision=Decimal("0.9000"),
        exception_detection_recall=Decimal("0.9000"),
        exception_detection_f1=Decimal("0.9000"),
    )

    unsafe_score = UnsafeAutoMatchMetrics(
        unsafe_auto_match_count=2,
        total_auto_match_count=80,
        unsafe_auto_match_rate=Decimal("0.0250"),
    )

    batch_score = BatchIntegrityScorecard(
        total_batches=5,
        clean_batches=4,
        partial_batches=1,
        orphan_entity_batches=0,
        duplicate_entity_batches=0,
        missing_settlement_batches=0,
        temporal_anomaly_batches=0,
        fully_reconciled_rate=Decimal("0.8000"),
    )

    tp_res = ThroughputResult(
        total_records=100,
        wall_clock_seconds=Decimal("0.0500"),
        records_per_second=Decimal("2000.00"),
        avg_latency_ms=Decimal("0.5000"),
        p95_latency_ms=Decimal("0.8000"),
        runs_averaged=3,
    )

    psr = PerSeedResult(
        seed=42,
        dataset_version="1.0",
        config_hash="abc",
        reconciliation_scorecard=recon_score,
        exception_scorecard=exc_score,
        unsafe_auto_match_metrics=unsafe_score,
        batch_integrity_scorecard=batch_score,
        processed_at=datetime.now(),
    )

    mock_service.evaluate_seed.return_value = psr
    mock_harness.run.return_value = tp_res

    code = main(["--config", str(dummy_config_path), "--seed", "42"])
    assert code == 0
    mock_service.evaluate_seed.assert_called_once()
    mock_harness.run.assert_called_once()


@patch("scripts.run_benchmark.EvaluationService")
@patch("scripts.run_benchmark.BenchmarkHarness")
@patch("scripts.run_benchmark.MultiSeedAggregator")
def test_successful_multi_seed_mocked(mock_agg_cls, mock_harness_cls, mock_service_cls, dummy_config_path):
    mock_service = mock_service_cls.return_value
    mock_harness = mock_harness_cls.return_value
    mock_agg = mock_agg_cls.return_value

    from app.models.evaluation import PerSeedResult, AggregateEvaluationReport, MetricSummary

    psr1 = MagicMock(spec=PerSeedResult, seed=100, throughput=None)
    psr2 = MagicMock(spec=PerSeedResult, seed=101, throughput=None)

    mock_service.evaluate_seed.side_effect = [psr1, psr2]
    mock_harness.run.return_value = MagicMock()

    summary = MetricSummary(
        mean=Decimal("0.9500"),
        median=Decimal("0.9500"),
        std=Decimal("0.0100"),
        min=Decimal("0.9400"),
        max=Decimal("0.9600"),
        seeds_with_data=2,
    )

    mock_report = MagicMock(spec=AggregateEvaluationReport)
    mock_report.run_id = "CLI_BENCHMARK_RUN"
    mock_report.seed_list = [100, 101]
    mock_report.seed_count = 2
    mock_report.partition = "evaluation"
    mock_report.timestamp_utc = datetime.now()
    mock_report.notes = []

    # Bind summary fields
    mock_report.auto_match_precision = summary
    mock_report.auto_match_recall = summary
    mock_report.reconciliation_f1 = summary
    mock_report.unsafe_auto_match_rate = summary
    mock_report.fully_reconciled_rate = summary
    mock_report.exception_detection_precision = summary
    mock_report.exception_detection_recall = summary
    mock_report.exception_detection_f1 = summary

    # In single run return two psr with tp
    from app.models.evaluation import ThroughputResult
    tp_res1 = ThroughputResult(
        total_records=100,
        wall_clock_seconds=Decimal("0.05"),
        records_per_second=Decimal("2000.0"),
        avg_latency_ms=Decimal("0.5"),
    )
    psr1.throughput = tp_res1
    psr2.throughput = tp_res1
    mock_report.per_seed_results = [psr1, psr2]

    mock_agg.aggregate.return_value = mock_report

    code = main(["--config", str(dummy_config_path), "--seeds", "100,101"])
    assert code == 0
    assert mock_service.evaluate_seed.call_count == 2
    mock_agg.aggregate.assert_called_once()


@patch("scripts.run_benchmark.EvaluationService")
def test_non_zero_failure_behavior(mock_service_cls, dummy_config_path):
    mock_service = mock_service_cls.return_value
    mock_service.evaluate_seed.side_effect = RuntimeError("Simulated evaluator crash")

    code = main(["--config", str(dummy_config_path), "--seed", "42"])
    assert code != 0
