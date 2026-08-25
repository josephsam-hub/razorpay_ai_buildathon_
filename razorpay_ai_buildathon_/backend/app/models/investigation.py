"""
LedgerLens — Investigation Models
=================================
Defines the Pydantic schemas for the agentic investigation context and structured output.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ValidationError, field_validator
from app.models.decisions import BatchReconciliationResult
from app.models.reconciliation_input import ReconciliationBatch


class InvestigationContext(BaseModel):
    model_config = {
        "frozen": True,
        "arbitrary_types_allowed": True,
    }

    batch_id: str = Field(..., description="ID of the target batch being investigated")
    target_payment_id: str = Field(..., description="Payment ID that is the focus of investigation")
    reconciliation_result: BatchReconciliationResult = Field(..., description="The outcome of the deterministic matching engine")
    batch: ReconciliationBatch = Field(..., description="The raw observed financial records batch")
    allowed_payment_ids: frozenset[str] = Field(..., description="Payment IDs allowed to be accessed within this context")

    @field_validator("batch_id", "target_payment_id")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("Field cannot be empty or whitespace.")
        return v


class PaymentEvidenceResponse(BaseModel):
    payment: Dict[str, Any]
    decision: Optional[Dict[str, Any]] = None
    evidence_card: Optional[Dict[str, Any]] = None
    matched_records: Dict[str, Optional[Dict[str, Any]]]


class PolicyRulesResponse(BaseModel):
    rules: Dict[str, Dict[str, Any]]


class BatchOrphansResponse(BaseModel):
    duplicate_bank_entries: List[Dict[str, Any]]
    duplicate_ledger_entries: List[Dict[str, Any]]
    orphan_bank_entries: List[Dict[str, Any]]
    orphan_settlements: List[Dict[str, Any]]
    orphan_ledger_entries: List[Dict[str, Any]]


class InvestigationReport(BaseModel):
    """
    Structured explanation and resolution report for exceptions.
    Separates deterministic matching confidence from LLM heuristic confidence.

    This report is never authoritative over reconciliation decisions,
    exception codes, or financial amounts. Extra LLM fields are ignored.
    """
    model_config = {
        "frozen": True,
        "extra": "ignore",
    }

    payment_id: str = Field(..., description="The target payment ID investigated")
    batch_id: str = Field(..., description="The target batch ID")
    status: Literal["AVAILABLE", "UNAVAILABLE", "INVALID_OUTPUT"] = Field(
        ...,
        description="AVAILABLE if LLM succeeded, UNAVAILABLE if Gemini failed, INVALID_OUTPUT if validation failed"
    )
    reconciliation_confidence: Decimal = Field(
        ...,
        description="Authoritative matching confidence from deterministic rules [0.00, 1.00]"
    )
    investigation_confidence: Optional[Decimal] = Field(
        None,
        description="AI's reasoning confidence about the root cause classification [0.00, 1.00]"
    )
    agent_explanation: Optional[str] = Field(
        None,
        description="NLP explanation of discrepancy findings. Never contains instructions."
    )
    suggested_actions: List[str] = Field(
        default_factory=list,
        description="Recommended resolution steps for reviewers"
    )
    root_cause: Optional[Literal[
        "AMOUNT_MISMATCH",
        "DATE_WINDOW_VIOLATION",
        "DUPLICATE_TRANSACTION",
        "MISSING_RECORD",
        "FEE_CONTRACT_VARIANCE",
        "ORPHAN_RECORD",
        "UNKNOWN"
    ]] = Field(None, description="Discrepancy category classification")
    violated_rules: List[str] = Field(
        default_factory=list,
        description="Rule IDs triggered, traced directly from deterministic cards"
    )

    @field_validator("reconciliation_confidence")
    @classmethod
    def validate_rec_confidence(cls, v: Decimal) -> Decimal:
        if v.is_nan() or v.is_infinite():
            raise ValueError("Reconciliation confidence cannot be NaN or Infinity")
        if v < Decimal("0.00") or v > Decimal("1.00"):
            raise ValueError("Reconciliation confidence must be in range [0.00, 1.00]")
        return v

    @field_validator("investigation_confidence")
    @classmethod
    def validate_inv_confidence(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            if v.is_nan() or v.is_infinite():
                raise ValueError("Investigation confidence cannot be NaN or Infinity")
            if v < Decimal("0.00") or v > Decimal("1.00"):
                raise ValueError("Investigation confidence must be in range [0.00, 1.00]")
        return v

    @classmethod
    def build_fallback(
        cls,
        batch_id: str,
        payment_id: str,
        reconciliation_confidence: Decimal,
        status: Literal["UNAVAILABLE", "INVALID_OUTPUT"],
        error_message: str,
    ) -> InvestigationReport:
        """Constructs a safe fallback report when Gemini is offline or yields bad data."""
        return cls(
            payment_id=payment_id,
            batch_id=batch_id,
            status=status,
            reconciliation_confidence=reconciliation_confidence,
            investigation_confidence=None,
            agent_explanation=f"AI investigation fallback: {error_message}",
            suggested_actions=["Refer to deterministic evidence card and exception records."],
            root_cause=None,
            violated_rules=[],
        )

    @classmethod
    def _authoritative_confidence(cls, context: InvestigationContext) -> Decimal:
        for dec in context.reconciliation_result.decisions:
            if dec.payment_id == context.target_payment_id:
                return dec.confidence
        for card in context.reconciliation_result.evidence_cards:
            if card.payment_id == context.target_payment_id:
                return card.confidence
        return Decimal("0.00")

    @classmethod
    def _allowed_rule_ids(cls, context: InvestigationContext) -> set[str]:
        allowed: set[str] = set()
        for card in context.reconciliation_result.evidence_cards:
            if card.payment_id != context.target_payment_id:
                continue
            allowed.update(card.rules_triggered)
            for finding in card.validation_findings:
                if not finding.passed:
                    allowed.add(finding.rule_id)
        return allowed

    @classmethod
    def from_llm_output(
        cls,
        context: InvestigationContext,
        payload: object,
        error_message: str = "Malformed Gemini output",
    ) -> InvestigationReport:
        """
        Bind an LLM payload to InvestigationContext.

        Identity fields and reconciliation_confidence always come from the
        deterministic context. Hallucinated payment IDs, exception codes,
        and financial amounts are dropped. Invalid payloads yield INVALID_OUTPUT
        without changing the underlying reconciliation result.
        """
        rec_confidence = cls._authoritative_confidence(context)
        if not isinstance(payload, dict):
            return cls.build_fallback(
                batch_id=context.batch_id,
                payment_id=context.target_payment_id,
                reconciliation_confidence=rec_confidence,
                status="INVALID_OUTPUT",
                error_message=error_message,
            )

        try:
            raw_conf = payload.get("investigation_confidence")
            investigation_confidence = (
                Decimal(str(raw_conf)) if raw_conf is not None else None
            )
            root_cause = payload.get("root_cause")
            allowed_roots = {
                "AMOUNT_MISMATCH",
                "DATE_WINDOW_VIOLATION",
                "DUPLICATE_TRANSACTION",
                "MISSING_RECORD",
                "FEE_CONTRACT_VARIANCE",
                "ORPHAN_RECORD",
                "UNKNOWN",
            }
            if root_cause is not None and root_cause not in allowed_roots:
                return cls.build_fallback(
                    batch_id=context.batch_id,
                    payment_id=context.target_payment_id,
                    reconciliation_confidence=rec_confidence,
                    status="INVALID_OUTPUT",
                    error_message="Unsupported root_cause from Gemini output",
                )

            raw_rules = payload.get("violated_rules") or []
            if not isinstance(raw_rules, list) or any(not isinstance(r, str) for r in raw_rules):
                return cls.build_fallback(
                    batch_id=context.batch_id,
                    payment_id=context.target_payment_id,
                    reconciliation_confidence=rec_confidence,
                    status="INVALID_OUTPUT",
                    error_message="violated_rules must be a list of rule IDs",
                )
            allowed_rules = cls._allowed_rule_ids(context)
            violated_rules = [r for r in raw_rules if r in allowed_rules]

            explanation = payload.get("agent_explanation")
            if explanation is not None and not isinstance(explanation, str):
                return cls.build_fallback(
                    batch_id=context.batch_id,
                    payment_id=context.target_payment_id,
                    reconciliation_confidence=rec_confidence,
                    status="INVALID_OUTPUT",
                    error_message="agent_explanation must be a string",
                )
            actions = payload.get("suggested_actions") or []
            if not isinstance(actions, list) or any(not isinstance(a, str) for a in actions):
                return cls.build_fallback(
                    batch_id=context.batch_id,
                    payment_id=context.target_payment_id,
                    reconciliation_confidence=rec_confidence,
                    status="INVALID_OUTPUT",
                    error_message="suggested_actions must be a list of strings",
                )

            return cls(
                payment_id=context.target_payment_id,
                batch_id=context.batch_id,
                status="AVAILABLE",
                reconciliation_confidence=rec_confidence,
                investigation_confidence=investigation_confidence,
                agent_explanation=explanation,
                suggested_actions=list(actions),
                root_cause=root_cause,
                violated_rules=violated_rules,
            )
        except (TypeError, ValueError, ValidationError):
            return cls.build_fallback(
                batch_id=context.batch_id,
                payment_id=context.target_payment_id,
                reconciliation_confidence=rec_confidence,
                status="INVALID_OUTPUT",
                error_message=error_message,
            )
