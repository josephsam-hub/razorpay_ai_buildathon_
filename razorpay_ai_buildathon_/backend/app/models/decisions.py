"""
LedgerLens Phase 3 — Reconciliation Decision Models
=====================================================
Pydantic models for reconciliation outputs:
  - MatchEvidence               one atomic rule evaluation
  - EvidenceCard                complete evidence record per decision (Fix 7: extended)
  - ReconciliationDecision      lightweight structured output per payment
  - BatchReconciliationResult   aggregate over a full batch

DESIGN RULES:
  - All financial values use decimal.Decimal — never float.
  - confidence is Decimal in [0.00, 1.00].
  - Decision labels: only AUTO_MATCH, HUMAN_REVIEW, ABSTAIN (no AGENT_REVIEW in Phase 3).
  - processed_at timestamp is written after the decision; it never affects logic.
  - Models are frozen (immutable after construction).

CONFIDENCE THRESHOLDS:
  TBD — REQUIRES SPECIFICATION.
  Phase 3.1 does not apply unspecified numeric thresholds.
  Exact matches → confidence = Decimal("1.00") → AUTO_MATCH.
  All other cases → deterministic rule-based decision (see engine.py).

FIX 7 — EVIDENCE CARD IMPROVEMENTS:
  Added fields to allow a human reviewer to understand:
    WHAT matched   → evidence list, rules_triggered
    WHY it matched → notes, stage_reached, confidence
    WHAT differed  → amount_delta, date_delta_days, fee_delta
    WHICH alternatives existed → alternative_candidate_ids
    WHY the final decision was made → decision, discrepancy_codes, notes
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Decision label type alias — shared across models
# ---------------------------------------------------------------------------

DecisionLabel = Literal["AUTO_MATCH", "HUMAN_REVIEW", "ABSTAIN"]


# ---------------------------------------------------------------------------
# MatchEvidence — one atomic rule evaluation
# ---------------------------------------------------------------------------

class MatchEvidence(BaseModel):
    """
    One piece of evidence contributing to a reconciliation decision.

    Each rule evaluation (pass or fail) produces one MatchEvidence entry.
    The collection of these entries constitutes the full evidence trail.
    """

    model_config = {"frozen": True}

    rule_id: str = Field(description="e.g. R001, R002 — stable rule identifier")
    rule_description: str = Field(description="Human-readable rule explanation")
    matched: bool = Field(description="True if this rule evaluated positively")
    field_name: str = Field(description="Domain field checked by this rule")
    expected_value: str | None = Field(
        default=None,
        description="Value expected from the payment/settlement side (serialised to str)",
    )
    observed_value: str | None = Field(
        default=None,
        description="Value actually seen in the bank/ledger/settlement record",
    )
    score_contribution: Decimal = Field(
        description="Contribution this rule makes to total confidence (0.00 if not matched)",
    )

    @field_validator("score_contribution")
    @classmethod
    def contribution_non_negative(cls, v: Decimal) -> Decimal:
        if v < Decimal("0"):
            raise ValueError(f"score_contribution must be >= 0, got {v}")
        return v


# ---------------------------------------------------------------------------
# ValidationFinding — focused finding with explicit evidence
# ---------------------------------------------------------------------------

class ValidationFinding(BaseModel):
    """
    Focused validation finding with explicit evidence.
    """
    model_config = {"frozen": True}

    rule_id: str = Field(description="e.g. V001 - validation rule identifier")
    rule_description: str
    passed: bool
    severity: Literal["INFO", "WARNING", "ERROR"]
    expected_relationship: str
    observed_relationship: str
    delta: str | None = None
    affected_record_ids: list[str] = Field(default_factory=list)
    discrepancy_code: str | None = None


# ---------------------------------------------------------------------------
# EvidenceCard — complete evidence record for one reconciliation decision
# ---------------------------------------------------------------------------

class EvidenceCard(BaseModel):
    """
    Complete evidence record for one payment reconciliation decision.

    Source: Documentation-21-08-26.md §10 Evidence Card specification.

    Fix 7 additions:
      amount_delta           — Decimal difference between bank credit and settlement net.
                               None when bank or settlement is absent.
                               Positive means bank credited MORE than expected.
      date_delta_days        — Integer difference (settlement_date - payment_date).
                               None when settlement is absent.
                               Negative means settlement is dated BEFORE payment.
      fee_delta              — Decimal difference in fee (settlement fee vs expected).
                               None unless a fee variance is detected.
                               Allows reviewer to see exactly how much the fee drifted.
      alternative_candidate_ids — IDs of any other settlement/bank entries that were
                               considered but not selected as the primary match.
                               Populated when duplicates or orphans exist.

    INVARIANTS:
      - If decision == "AUTO_MATCH", matched_settlement_id must not be None.
      - confidence must be in [0.00, 1.00].
      - processed_at is written after decision; must not affect matching.
      - amount_delta uses Decimal — never float.
    """

    model_config = {"frozen": True}

    audit_id: str = Field(description="AUD_YYYYMMDD_NNNN — unique audit identifier")
    payment_id: str = Field(description="Reconciliation anchor")
    decision: DecisionLabel
    confidence: Decimal = Field(description="0.00 – 1.00, 2 decimal places")

    # Matched record IDs (set on AUTO_MATCH; None otherwise)
    matched_settlement_id: str | None = None
    matched_bank_entry_id: str | None = None
    matched_ledger_entry_id: str | None = None

    # Evidence detail
    evidence: list[MatchEvidence] = Field(default_factory=list)
    rules_triggered: list[str] = Field(
        default_factory=list,
        description="Rule IDs that evaluated as matched=True",
    )
    stage_reached: Literal["exact", "composite", "no_match"] = Field(
        description="The highest matching stage executed for this payment",
    )

    # Discrepancy codes detected by the engine
    # NOTE: These are reconciliation-layer codes (rec:E001–rec:E010),
    # distinct from the generator's corruption E-codes.
    # See engine.py for the reconciliation exception code definitions.
    discrepancy_codes: list[str] = Field(
        default_factory=list,
        description="Reconciliation exception codes detected (empty for clean AUTO_MATCH)",
    )

    notes: str = Field(default="", description="Human-readable explanation")

    # ------------------------------------------------------------------
    # Fix 7 — Diagnostic delta fields for human reviewers
    # ------------------------------------------------------------------

    amount_delta: Decimal | None = Field(
        default=None,
        description=(
            "Fix 7: bank_credit_amount - settlement_net_amount. "
            "None when bank or settlement absent. "
            "Non-zero indicates rec:E002 (amount mismatch). "
            "Always Decimal — never float."
        ),
    )

    date_delta_days: int | None = Field(
        default=None,
        description=(
            "Fix 7: (settlement_date - payment_date).days. "
            "None when settlement absent. "
            "Negative means settlement is dated before payment (anomaly). "
            "Beyond SETTLEMENT_DATE_MAX_DAYS_AFTER_PAYMENT triggers rec:E004."
        ),
    )

    fee_delta: Decimal | None = Field(
        default=None,
        description=(
            "Fix 7: difference between expected and observed fee amount. "
            "Populated when settlement fee variance is detected. "
            "Always Decimal — never float."
        ),
    )

    alternative_candidate_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Fix 7: IDs of alternative settlement/bank entries considered "
            "but not selected. Populated when duplicates or orphans exist. "
            "Allows reviewer to see competing candidates."
        ),
    )

    validation_findings: list[ValidationFinding] = Field(
        default_factory=list,
        description="Focused validation findings with explicit delta, severity and discrepancy code.",
    )

    # Timestamp — written after decision; never used in matching
    processed_at: datetime = Field(description="UTC timestamp of decision — audit only")

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") <= v <= Decimal("1")):
            raise ValueError(f"confidence must be in [0.00, 1.00], got {v}")
        return v


# ---------------------------------------------------------------------------
# ReconciliationDecision — lightweight per-payment output
# ---------------------------------------------------------------------------

class ReconciliationDecision(BaseModel):
    """
    Lightweight structured output for one payment — suitable for batch
    aggregation, API responses, and evaluation comparison.
    """

    model_config = {"frozen": True}

    payment_id: str
    decision: DecisionLabel
    confidence: Decimal
    exception_codes: list[str] = Field(default_factory=list)
    audit_id: str = Field(description="FK → EvidenceCard.audit_id")

    @field_validator("confidence")
    @classmethod
    def confidence_in_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") <= v <= Decimal("1")):
            raise ValueError(f"confidence must be in [0.00, 1.00], got {v}")
        return v


# ---------------------------------------------------------------------------
# OrphanRecord — Fix 4: represents an entity not reachable from any payment
# ---------------------------------------------------------------------------

class OrphanRecord(BaseModel):
    """
    An entity (bank entry, settlement, or ledger entry) found in the
    ObservedWorld but not reachable from any payment in the current batch.

    Fix 4: orphan records are never silently discarded.
    Each one produces an OrphanRecord for audit and exception routing.
    """

    model_config = {"frozen": True}

    orphan_id: str = Field(description="ORF_YYYYMMDD_NNNN — unique orphan record ID")
    entity_type: Literal["bank_entry", "settlement", "ledger_entry"]
    entity_id: str = Field(description="Primary key of the orphaned entity")
    unmatched_ref: str = Field(
        description=(
            "The reference that has no match: "
            "settlement_ref for bank/settlement orphans, "
            "payment_id for ledger orphans."
        )
    )
    exception_code: str = Field(
        description="rec:E008 (Unknown transaction) for orphan bank entries; "
                    "rec:E010 (Insufficient evidence) for other orphan types."
    )
    notes: str = ""


# ---------------------------------------------------------------------------
# BatchReconciliationResult — aggregate over a full batch
# ---------------------------------------------------------------------------

class BatchReconciliationResult(BaseModel):
    """
    Aggregate metrics and individual decisions for a full batch run.

    Evaluation metrics follow Documentation-21-08-26.md §12:
      match_rate      = auto_matched / total_records
      exception_rate  = (human_review + abstained) / total_records

    Fix 4: orphan_records contains all entities not reachable from payments.
    """

    model_config = {"frozen": True}

    batch_id: str = Field(description="Unique identifier for this batch run")
    total_records: int
    auto_matched: int
    human_review: int
    abstained: int

    # One decision per payment, ordered by payment_id (deterministic)
    decisions: list[ReconciliationDecision] = Field(default_factory=list)
    evidence_cards: list[EvidenceCard] = Field(default_factory=list)

    # Fix 4 — orphan entities not reachable from any payment
    orphan_records: list[OrphanRecord] = Field(
        default_factory=list,
        description="Fix 4: entities with no matching payment — never silently discarded.",
    )

    match_rate: Decimal = Field(description="auto_matched / total_records (0.00 if empty)")
    exception_rate: Decimal = Field(
        description="(human_review + abstained) / total_records (0.00 if empty)"
    )

    processed_at: datetime = Field(description="UTC timestamp of batch completion")

    @field_validator("match_rate", "exception_rate")
    @classmethod
    def rate_in_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0") <= v <= Decimal("1")):
            raise ValueError(f"rate must be in [0.00, 1.00], got {v}")
        return v
