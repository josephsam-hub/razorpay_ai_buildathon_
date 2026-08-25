"""
LedgerLens Phase 3.2 — Evaluation Domain Models
=================================================
Pydantic models for the evaluation layer output.

GROUND-TRUTH ISOLATION:
  These models are populated by the Evaluator only.
  The reconciliation engine (app/core/reconciliation/*) must NEVER import
  from this module.

DESIGN RULES:
  - All fractional metrics are Decimal | None.
  - None is returned on zero-denominator — never 0.0 or NaN.
  - insufficient_data=True signals a None metric due to zero denominator.
  - Models are frozen (immutable after construction).
  - Financial amounts are Decimal — never float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Payment-level outcome codes (Taxonomy §10)
# ---------------------------------------------------------------------------

PaymentOutcome = Literal[
    "TP_MATCH",       # gt=AUTO_MATCH  AND engine=AUTO_MATCH
    "FP_MATCH",       # gt=HUMAN_REVIEW AND engine=AUTO_MATCH  ← unsafe auto-match
    "TN_EXCEPTION",   # gt=HUMAN_REVIEW AND engine=HUMAN_REVIEW
    "ABST_CORRUPT",   # gt=HUMAN_REVIEW AND engine=ABSTAIN
    "FN_MISS_CLEAN",  # gt=AUTO_MATCH  AND engine=HUMAN_REVIEW
    "ABST_CLEAN",     # gt=AUTO_MATCH  AND engine=ABSTAIN
]

ExceptionClassification = Literal[
    "CORRECT_CODE",  # engine exception_codes ∩ expected_rec_codes is non-empty
    "WRONG_CODE",    # engine detected exception but codes don't intersect expected
    "NO_CODE",       # engine correctly routed to HUMAN_REVIEW but exception_codes empty
    "N_A",           # not applicable (TP_MATCH, FP_MATCH, ABST_CLEAN)
]

OrphanOutcome = Literal[
    "ORPHAN_DETECTED",  # injected orphan appears in orphan_records
    "ORPHAN_MISSED",    # injected orphan not surfaced
    "FALSE_ORPHAN",     # engine surfaced an orphan that was not injected
]

BatchFinding = Literal[
    "BATCH_CLEAN",
    "BATCH_PARTIAL",
    "BATCH_ORPHAN_ENTITY",
    "BATCH_DUPLICATE_ENTITY",
    "BATCH_MISSING_SETTLEMENT",
    "BATCH_TEMPORAL_ANOMALY",
]

EntityType = Literal["payment", "settlement", "bank_entry", "ledger_entry", "batch"]


# ---------------------------------------------------------------------------
# EntityFinding — one entity-level evaluation record
# ---------------------------------------------------------------------------

class EntityFinding(BaseModel):
    """Entity-aware evaluation finding (plan §3, Revision 1)."""

    model_config = {"frozen": True}

    entity_type: EntityType
    record_id: str
    payment_id: str | None = None          # null for orphan bank entries / settlements
    related_record_ids: list[str] = Field(default_factory=list)
    payment_outcome: PaymentOutcome | None = None      # set for entity_type="payment"
    exception_classification: ExceptionClassification = "N_A"
    orphan_outcome: OrphanOutcome | None = None        # set for entity_type="bank_entry" orphans
    expected_outcome: str = ""
    observed_outcome: str = ""
    corruption_type: str | None = None     # generator E-code name if applicable
    corruption_gen_code: str | None = None # "E001"–"E008"
    expected_rec_codes: list[str] = Field(default_factory=list)
    observed_rec_codes: list[str] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# BatchIntegrityResult — one settlement batch
# ---------------------------------------------------------------------------

class BatchIntegrityResult(BaseModel):
    """Integrity finding for a single settlement batch."""

    model_config = {"frozen": True}

    settlement_id: str | None = None    # None if settlement missing
    settlement_ref: str | None = None
    payment_ids: list[str] = Field(default_factory=list)
    findings: list[BatchFinding] = Field(default_factory=list)
    total_payments_in_batch: int = 0
    auto_matched_in_batch: int = 0
    human_review_in_batch: int = 0
    abstained_in_batch: int = 0
    has_orphan_entity: bool = False
    has_duplicate_entity: bool = False
    has_temporal_anomaly: bool = False

    @property
    def is_clean(self) -> bool:
        return "BATCH_CLEAN" in self.findings and len(self.findings) == 1


# ---------------------------------------------------------------------------
# ReconciliationScorecard — Scorecard A (payment-level)
# ---------------------------------------------------------------------------

class ReconciliationScorecard(BaseModel):
    """
    Scorecard A: Did the engine make correct payment-level decisions?
    Answers: TP/FP/TN/FN classification across all payments.
    """

    model_config = {"frozen": True}

    total_payments: int
    clean_payments: int
    corrupted_payments: int

    # Decision distribution
    auto_matched_count: int
    human_review_count: int
    abstained_count: int

    # Accuracy counts
    correct_match_count: int        # TP_MATCH
    incorrect_match_count: int      # FP_MATCH
    missed_match_count: int         # FN_MISS_CLEAN
    correct_exception_count: int    # TN_EXCEPTION
    false_exception_count: int      # FN_MISS_CLEAN (clean → HUMAN_REVIEW or ABSTAIN)
    abstained_clean_count: int      # ABST_CLEAN
    abstained_corrupt_count: int    # ABST_CORRUPT

    # Computed metrics (None = insufficient data)
    auto_match_precision: Decimal | None
    auto_match_recall: Decimal | None
    reconciliation_f1: Decimal | None
    resolution_rate: Decimal

    # Zero-denominator flags
    precision_insufficient_data: bool = False
    recall_insufficient_data: bool = False
    f1_insufficient_data: bool = False


# ---------------------------------------------------------------------------
# UnsafeAutoMatchMetrics — critical finance-safety metric
# ---------------------------------------------------------------------------

class UnsafeAutoMatchMetrics(BaseModel):
    """
    Measures incorrect AUTO_MATCH decisions on corrupted records.
    An unsafe auto-match is a direct financial risk (plan §7, Revision 5).
    """

    model_config = {"frozen": True}

    unsafe_auto_match_count: int
    total_auto_match_count: int
    unsafe_auto_match_rate: Decimal | None   # null if no auto-matches
    insufficient_data: bool = False
    unsafe_auto_match_by_corruption: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# PerCorruptionMetric — one row per generator E-code type
# ---------------------------------------------------------------------------

class PerCorruptionMetric(BaseModel):
    """Per-corruption-type breakdown for Scorecard B."""

    model_config = {"frozen": True}

    corruption_type: str
    gen_code: str                           # "E001"–"E008"
    expected_rec_codes: list[str]
    injected_count: int
    correctly_detected_count: int
    missed_count: int
    auto_matched_incorrectly_count: int     # FP_MATCH for this type
    correct_code_classification_count: int
    wrong_code_classification_count: int
    no_code_count: int
    detection_rate: Decimal | None          # null if injected_count == 0
    unsafe_auto_match_count: int
    insufficient_data: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# PerEntityMetric — one row per entity type
# ---------------------------------------------------------------------------

class PerEntityMetric(BaseModel):
    """Per-entity-type breakdown across the batch."""

    model_config = {"frozen": True}

    entity_type: EntityType
    total_observed: int
    corrupted_count: int
    correctly_handled_count: int
    incorrectly_handled_count: int
    orphan_injected_count: int
    orphan_detected_count: int
    orphan_missed_count: int
    insufficient_data: bool = False


# ---------------------------------------------------------------------------
# ExceptionScorecard — Scorecard B (entity-level)
# ---------------------------------------------------------------------------

class ExceptionScorecard(BaseModel):
    """
    Scorecard B: Did the engine catch all exceptions with correct codes?
    Operates on both payment-level and entity-level orphan records.
    """

    model_config = {"frozen": True}

    total_injected_exceptions: int   # corrupted payments + injected orphan entities
    correctly_detected_exceptions: int
    missed_exceptions: int
    incorrectly_classified_exceptions: int  # detected but wrong rec: code
    no_code_exceptions: int                 # detected but no rec: code
    false_exception_detections: int         # exception on a clean payment

    exception_detection_precision: Decimal | None
    exception_detection_recall: Decimal | None
    exception_detection_f1: Decimal | None

    precision_insufficient_data: bool = False
    recall_insufficient_data: bool = False
    f1_insufficient_data: bool = False


# ---------------------------------------------------------------------------
# BatchIntegrityScorecard — batch-level summary
# ---------------------------------------------------------------------------

class BatchIntegrityScorecard(BaseModel):
    """Batch-integrity evaluation (plan §8, Revision 7)."""

    model_config = {"frozen": True}

    total_batches: int
    clean_batches: int
    partial_batches: int
    orphan_entity_batches: int
    duplicate_entity_batches: int
    missing_settlement_batches: int
    temporal_anomaly_batches: int
    fully_reconciled_rate: Decimal | None   # clean_batches / total_batches; null if 0
    insufficient_data: bool = False
    note: str = (
        "fully_reconciled_rate != auto_match_rate — "
        "orphan/duplicate entities prevent full clean batch status"
    )


# ---------------------------------------------------------------------------
# ThroughputResult — benchmark measurement
# ---------------------------------------------------------------------------

class ThroughputResult(BaseModel):
    """Throughput measurement for one dataset size."""

    model_config = {"frozen": True}

    total_records: int
    wall_clock_seconds: Decimal
    records_per_second: Decimal
    avg_latency_ms: Decimal
    p95_latency_ms: Decimal | None = None   # only set in benchmark mode
    benchmark_mode: bool = False
    platform: str = ""
    python_version: str = ""
    runs_averaged: int = 1


# ---------------------------------------------------------------------------
# PerSeedResult — complete evaluation result for one seed
# ---------------------------------------------------------------------------

class PerSeedResult(BaseModel):
    """Full evaluation result for one generated dataset (one seed)."""

    model_config = {"frozen": True}

    seed: int
    dataset_version: str
    config_hash: str
    record_counts: dict[str, int] = Field(default_factory=dict)
    corruption_profile: dict[str, int] = Field(default_factory=dict)

    entity_counts: dict[str, int] = Field(default_factory=dict)
    decision_distribution: dict[str, int] = Field(default_factory=dict)

    reconciliation_scorecard: ReconciliationScorecard
    exception_scorecard: ExceptionScorecard
    unsafe_auto_match_metrics: UnsafeAutoMatchMetrics
    batch_integrity_scorecard: BatchIntegrityScorecard

    per_corruption_metrics: list[PerCorruptionMetric] = Field(default_factory=list)
    per_entity_metrics: list[PerEntityMetric] = Field(default_factory=list)
    batch_integrity_details: list[BatchIntegrityResult] = Field(default_factory=list)

    entity_findings: list[EntityFinding] = Field(
        default_factory=list,
        description="Detailed per-entity evaluation findings",
    )
    unresolved_entities: list[dict] = Field(
        default_factory=list,
        description="Engine output for unresolved payments and orphan records",
    )

    throughput: ThroughputResult | None = None
    processed_at: datetime | None = None


# ---------------------------------------------------------------------------
# MetricSummary — statistics across seeds for one scalar metric
# ---------------------------------------------------------------------------

class MetricSummary(BaseModel):
    """Aggregated statistics for one numeric metric across seeds."""

    model_config = {"frozen": True}

    mean: Decimal | None
    median: Decimal | None
    std: Decimal | None
    min: Decimal | None
    max: Decimal | None
    confidence_interval_95: tuple[Decimal, Decimal] | None = None
    seeds_with_data: int = 0
    seeds_with_insufficient_data: int = 0


# ---------------------------------------------------------------------------
# AggregateEvaluationReport — multi-seed summary
# ---------------------------------------------------------------------------

class AggregateEvaluationReport(BaseModel):
    """Aggregate report across multiple seeds (plan §12)."""

    model_config = {"frozen": True}

    run_id: str
    evaluation_version: str = "0.1.0"
    engine_commit: str = ""
    python_version: str = ""
    platform: str = ""
    timestamp_utc: datetime
    partition: Literal["calibration", "evaluation", "holdout"]
    seed_list: list[int]
    seed_count: int

    per_seed_results: list[PerSeedResult] = Field(default_factory=list)

    # Aggregated scorecard metrics
    auto_match_precision: MetricSummary | None = None
    auto_match_recall: MetricSummary | None = None
    reconciliation_f1: MetricSummary | None = None
    unsafe_auto_match_rate: MetricSummary | None = None
    exception_detection_precision: MetricSummary | None = None
    exception_detection_recall: MetricSummary | None = None
    exception_detection_f1: MetricSummary | None = None
    fully_reconciled_rate: MetricSummary | None = None

    # Composite score distributions (calibration only)
    composite_score_distribution: dict[str, list[str]] | None = Field(
        default=None,
        description="clean_payment_scores and corrupt_payment_scores — calibration only",
    )

    notes: list[str] = Field(default_factory=list)
