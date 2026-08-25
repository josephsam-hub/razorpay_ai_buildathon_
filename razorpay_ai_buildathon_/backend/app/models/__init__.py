"""
Models package — Phase 3.1 reconciliation + Phase 3.2 evaluation domain models.

Pydantic domain models:
  canonical.py   — CanonicalTransaction (normalised per-payment view)
  decisions.py   — MatchEvidence, EvidenceCard, ReconciliationDecision,
                   BatchReconciliationResult
  exceptions.py  — ExceptionRecord, reconciliation exception codes
  evaluation.py  — PerSeedResult, AggregateEvaluationReport, scorecards,
                   EntityFinding, ThroughputResult, MetricSummary, etc.
"""

from app.models.canonical import CanonicalTransaction
from app.models.decisions import (
    BatchReconciliationResult,
    DecisionLabel,
    EvidenceCard,
    MatchEvidence,
    ReconciliationDecision,
)
from app.models.exceptions import ExceptionRecord
from app.models.reconciliation_input import ReconciliationBatch, from_observed_world
from app.models.investigation import (
    InvestigationContext,
    PaymentEvidenceResponse,
    PolicyRulesResponse,
    BatchOrphansResponse,
    InvestigationReport,
)
from app.models.evaluation import (
    AggregateEvaluationReport,
    BatchIntegrityResult,
    BatchIntegrityScorecard,
    EntityFinding,
    ExceptionScorecard,
    MetricSummary,
    PerCorruptionMetric,
    PerEntityMetric,
    PerSeedResult,
    ReconciliationScorecard,
    ThroughputResult,
    UnsafeAutoMatchMetrics,
)

__all__ = [
    # Phase 3.1
    "CanonicalTransaction",
    "BatchReconciliationResult",
    "DecisionLabel",
    "EvidenceCard",
    "MatchEvidence",
    "ReconciliationDecision",
    "ExceptionRecord",
    "ReconciliationBatch",
    "from_observed_world",
    "InvestigationContext",
    "PaymentEvidenceResponse",
    "PolicyRulesResponse",
    "BatchOrphansResponse",
    "InvestigationReport",
    # Phase 3.2
    "AggregateEvaluationReport",
    "BatchIntegrityResult",
    "BatchIntegrityScorecard",
    "EntityFinding",
    "ExceptionScorecard",
    "MetricSummary",
    "PerCorruptionMetric",
    "PerEntityMetric",
    "PerSeedResult",
    "ReconciliationScorecard",
    "ThroughputResult",
    "UnsafeAutoMatchMetrics",
]
