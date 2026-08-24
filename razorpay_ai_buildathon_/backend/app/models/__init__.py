"""
Models package — Phase 3.1 reconciliation domain models.

Pydantic domain models:
  canonical.py  — CanonicalTransaction (normalised per-payment view)
  decisions.py  — MatchEvidence, EvidenceCard, ReconciliationDecision,
                  BatchReconciliationResult
  exceptions.py — ExceptionRecord, reconciliation exception codes
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

__all__ = [
    "CanonicalTransaction",
    "BatchReconciliationResult",
    "DecisionLabel",
    "EvidenceCard",
    "MatchEvidence",
    "ReconciliationDecision",
    "ExceptionRecord",
]
