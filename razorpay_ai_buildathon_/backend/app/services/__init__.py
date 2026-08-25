"""
Services package — Phase 3.1 reconciliation + Phase 3.2 evaluation services.

reconciliation.py — ReconciliationService (stateless, in-memory)
evaluation.py     — EvaluationService (stateless, in-memory; uses ground truth)

Planned (Phase 4):
  - AuditService
  - ExceptionService
  - AgentInvestigationService
"""

from app.services.reconciliation import ReconciliationService
from app.services.investigation import AgentInvestigationResult, AgentInvestigationService

__all__ = [
  "ReconciliationService",
  "EvaluationService",
  "AgentInvestigationResult",
  "AgentInvestigationService",
]


def __getattr__(name: str):
  if name == "EvaluationService":
    from app.services.evaluation import EvaluationService

    return EvaluationService
  raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
