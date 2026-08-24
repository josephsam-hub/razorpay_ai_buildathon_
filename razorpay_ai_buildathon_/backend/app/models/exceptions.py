"""
LedgerLens Phase 3 — Reconciliation Exception Model
=====================================================
ExceptionRecord represents a payment case that could not be auto-resolved.

IMPORTANT — E-CODE DISAMBIGUATION:
  The Documentation §11 defines a reconciliation-layer exception taxonomy
  (E001–E010) for the reconciliation engine's output.

  The Phase 2 generator uses a different E-code set (E001–E008) for
  labelling injected corruptions.

  These are TWO SEPARATE namespaces. To avoid confusion, reconciliation-layer
  codes are prefixed "rec:" in string values (e.g. "rec:E001") wherever both
  namespaces could appear in the same context.

  The reconciliation engine's own codes follow Documentation §11:
    rec:E001  Missing source record
    rec:E002  Amount mismatch
    rec:E003  Duplicate transaction
    rec:E004  Date-window violation
    rec:E005  Currency mismatch
    rec:E006  Conflicting references
    rec:E007  Multiple candidates
    rec:E008  Unknown transaction
    rec:E009  Settlement mismatch
    rec:E010  Insufficient evidence

  TBD — REQUIRES SPECIFICATION:
  Exact mapping between detected exact-match failures and these codes is
  specified in engine.py. The codes above are those defined in
  Documentation-21-08-26.md §11. No additional codes are invented here.

Exception lifecycle follows Documentation-21-08-26.md §11 state diagram:
  DETECTED → INVESTIGATING | AUTO_RESOLVED | ESCALATED
  INVESTIGATING → RESOLVED | ESCALATED
  ESCALATED → HUMAN_REVIEWED
  HUMAN_REVIEWED → RESOLVED | REJECTED
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Reconciliation exception code registry
# ---------------------------------------------------------------------------
# Source: Documentation-21-08-26.md §11
# Prefix "rec:" distinguishes from Phase 2 generator corruption codes.

REC_E001 = "rec:E001"   # Missing source record
REC_E002 = "rec:E002"   # Amount mismatch
REC_E003 = "rec:E003"   # Duplicate transaction
REC_E004 = "rec:E004"   # Date-window violation
REC_E005 = "rec:E005"   # Currency mismatch
REC_E006 = "rec:E006"   # Conflicting references
REC_E007 = "rec:E007"   # Multiple candidates
REC_E008 = "rec:E008"   # Unknown transaction
REC_E009 = "rec:E009"   # Settlement mismatch
REC_E010 = "rec:E010"   # Insufficient evidence

ALL_REC_CODES = frozenset({
    REC_E001, REC_E002, REC_E003, REC_E004, REC_E005,
    REC_E006, REC_E007, REC_E008, REC_E009, REC_E010,
})

ExceptionStatus = Literal[
    "DETECTED",
    "INVESTIGATING",
    "AUTO_RESOLVED",
    "ESCALATED",
    "RESOLVED",
    "REJECTED",
]


# ---------------------------------------------------------------------------
# ExceptionRecord
# ---------------------------------------------------------------------------

class ExceptionRecord(BaseModel):
    """
    A payment case that could not be automatically reconciled.

    Created by the engine for every HUMAN_REVIEW or ABSTAIN decision.
    The status lifecycle follows Documentation-21-08-26.md §11.

    Phase 3.1 creates ExceptionRecords with status=DETECTED.
    Status transitions (INVESTIGATING, ESCALATED, RESOLVED, REJECTED)
    are Phase 3.2+ concerns once the API and persistence layers exist.
    """

    model_config = {"frozen": True}

    exception_id: str = Field(description="EXC_YYYYMMDD_NNNN")
    payment_id: str = Field(description="Reconciliation anchor")
    exception_codes: list[str] = Field(
        default_factory=list,
        description="rec:E001-rec:E010 codes detected by the reconciliation engine",
    )
    status: ExceptionStatus = "DETECTED"
    audit_id: str | None = Field(
        default=None,
        description="FK → EvidenceCard.audit_id",
    )
    created_at: datetime = Field(description="UTC timestamp when exception was created")
    notes: str = ""
