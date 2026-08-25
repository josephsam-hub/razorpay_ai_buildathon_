"""
LedgerLens — Safe Read-Only Investigation Tools
===============================================
Implements the safe, narrow tool layer for agentic exception investigation.
All tool calls are scoped to an InvestigationContext to prevent cross-batch leaks.

Orphan and duplicate evidence is projected from the deterministic normaliser
(the same pass the reconciliation engine uses). Tools must not invent a
second matching implementation.
"""

from __future__ import annotations

from typing import Any

from app.core.reconciliation import policy
from app.core.reconciliation.normaliser import NormaliserResult, normalise
from app.models.investigation import (
    BatchOrphansResponse,
    InvestigationContext,
    PaymentEvidenceResponse,
    PolicyRulesResponse,
)

# Catalog of rules the investigation tool may describe.
# Descriptions are taken from the implemented engine/validation/composite
# modules. R012 is omitted because it was removed from exact matching.
RULES_METADATA: dict[str, dict[str, Any]] = {
    "R001": {
        "rule_id": "R001",
        "category": "exact",
        "description": "Settlement record exists for this payment.",
        "parameters": {},
    },
    "R002": {
        "rule_id": "R002",
        "category": "exact",
        "description": "Bank entry exists for the settlement.",
        "parameters": {},
    },
    "R003": {
        "rule_id": "R003",
        "category": "exact",
        "description": "Ledger entry exists for this payment.",
        "parameters": {},
    },
    "R004": {
        "rule_id": "R004",
        "category": "exact",
        "description": "BankEntry.settlement_ref matches Settlement.settlement_ref.",
        "parameters": {},
    },
    "R005": {
        "rule_id": "R005",
        "category": "exact",
        "description": "LedgerEntry.payment_id matches Payment.payment_id.",
        "parameters": {},
    },
    "R006": {
        "rule_id": "R006",
        "category": "exact",
        "description": "LedgerEntry.settlement_id matches Settlement.settlement_id.",
        "parameters": {},
    },
    "R007": {
        "rule_id": "R007",
        "category": "exact",
        "description": "Settlement.merchant_id matches Payment.merchant_id.",
        "parameters": {},
    },
    "R008": {
        "rule_id": "R008",
        "category": "exact",
        "description": (
            "Payment currency is INR (payment-side sanity check; Settlement and "
            "BankEntry do not carry currency in the current domain models)."
        ),
        "parameters": {},
    },
    "R009": {
        "rule_id": "R009",
        "category": "exact",
        "description": (
            "Gross amount check: for a single-payment settlement, payment_amount "
            "must exactly equal settlement_gross_amount; for a multi-payment "
            "settlement, settlement_gross_amount must be >= payment_amount "
            "(full batch-sum check is not implemented)."
        ),
        "parameters": {},
    },
    "R010": {
        "rule_id": "R010",
        "category": "exact",
        "description": "BankEntry.credit_amount == Settlement.net_amount.",
        "parameters": {},
    },
    "R011": {
        "rule_id": "R011",
        "category": "exact",
        "description": "LedgerEntry.allocated_amount <= Settlement.net_amount.",
        "parameters": {},
    },
    "R013": {
        "rule_id": "R013",
        "category": "exact",
        "description": (
            "Duplicate bank-entry guard: if more than one BankEntry shares this "
            "settlement_ref, exact match is blocked (rec:E003)."
        ),
        "parameters": {},
    },
    "R014": {
        "rule_id": "R014",
        "category": "exact",
        "description": (
            "Settlement net matches merchant contract fee rate "
            "(expected_fee = round_half_up(gross * fee_rate, 2); "
            "expected_net = gross - expected_fee). If fee_rate or gross is "
            "missing the rule is NOT_EVALUABLE and does not block AUTO_MATCH."
        ),
        "parameters": {},
    },
    "V001": {
        "rule_id": "V001",
        "category": "validation",
        "severity": "ERROR",
        "description": (
            "Settlement date must be on or after the latest payment date in the "
            "settlement batch (settlement_date >= latest_payment_date_in_settlement)."
        ),
        "parameters": {},
    },
    "V002": {
        "rule_id": "V002",
        "category": "validation",
        "severity": "WARNING",
        "description": (
            "Settlement date must equal latest_payment_date_in_settlement + "
            "settlement_cycle_days (exact cycle match, not a range)."
        ),
        "parameters": {},
    },
    "V003": {
        "rule_id": "V003",
        "category": "validation",
        "severity": "ERROR",
        "description": (
            "Bank entry value date must be within 0 to "
            f"{policy.V003_MAX_DAYS_AFTER_SETTLEMENT} days after the settlement date."
        ),
        "parameters": {
            "max_days_after_settlement": policy.V003_MAX_DAYS_AFTER_SETTLEMENT,
        },
    },
    "V004": {
        "rule_id": "V004",
        "category": "validation",
        "severity": "ERROR",
        "description": (
            "Ledger posting date must be within 0 to "
            f"{policy.V004_MAX_DAYS_AFTER_VALUE} days after the bank entry value date."
        ),
        "parameters": {
            "max_days_after_value": policy.V004_MAX_DAYS_AFTER_VALUE,
        },
    },
    "CS001": {
        "rule_id": "CS001",
        "category": "composite",
        "description": "merchant_id agreement across payment and settlement.",
        "parameters": {},
    },
    "CS002": {
        "rule_id": "CS002",
        "category": "composite",
        "description": "Payment currency is INR (composite sanity check).",
        "parameters": {},
    },
    "CS003": {
        "rule_id": "CS003",
        "category": "composite",
        "description": (
            "Amount proximity: score 1.00 if bank_credit_amount == settlement_net_amount; "
            "0.50 if net is present and bank is absent; 0.00 if net is missing. "
            "Composite scoring never produces AUTO_MATCH."
        ),
        "parameters": {},
    },
    "CS004": {
        "rule_id": "CS004",
        "category": "composite",
        "description": (
            "settlement_date within a linear-decay window of payment_date. "
            "Score is 1.00 at 0 days and 0.00 beyond the composite date-distance bound. "
            "Composite scoring never produces AUTO_MATCH."
        ),
        "parameters": {
            "max_date_distance_days": policy.CS004_MAX_DATE_DISTANCE_DAYS,
        },
    },
    "CS005": {
        "rule_id": "CS005",
        "category": "composite",
        "description": "settlement_ref structural link is present.",
        "parameters": {},
    },
}


def _dump(entity: Any) -> dict[str, Any]:
    return entity.model_dump(mode="json")


def _normaliser_result(context: InvestigationContext) -> NormaliserResult:
    """Same normalisation pass used by ReconciliationService / the engine."""
    return normalise(context.batch)


def fetch_payment_evidence(
    payment_id: str,
    context: InvestigationContext,
) -> PaymentEvidenceResponse:
    """
    Retrieves the evidence details, matching decision, and matched transaction entities
    for a specific payment ID inside the allowed context scope.
    """
    if payment_id not in context.allowed_payment_ids:
        raise ValueError("Access denied: Payment ID outside allowed context scope.")

    target_payment = None
    for p in context.batch.payments:
        if p.payment_id == payment_id:
            target_payment = p
            break

    if not target_payment:
        raise ValueError("Payment ID not found in current batch.")

    matched_decision = None
    for dec in context.reconciliation_result.decisions:
        if dec.payment_id == payment_id:
            matched_decision = dec
            break

    evidence_card = None
    for card in context.reconciliation_result.evidence_cards:
        if card.payment_id == payment_id:
            evidence_card = card
            break

    settlement = None
    bank_entry = None
    ledger_entry = None

    if evidence_card:
        if evidence_card.matched_settlement_id:
            for s in context.batch.settlements:
                if s.settlement_id == evidence_card.matched_settlement_id:
                    settlement = s
                    break
        if evidence_card.matched_bank_entry_id:
            for b in context.batch.bank_entries:
                if b.bank_entry_id == evidence_card.matched_bank_entry_id:
                    bank_entry = b
                    break
        if evidence_card.matched_ledger_entry_id:
            for le in context.batch.ledger_entries:
                if le.ledger_entry_id == evidence_card.matched_ledger_entry_id:
                    ledger_entry = le
                    break

    return PaymentEvidenceResponse(
        payment=_dump(target_payment),
        decision=_dump(matched_decision) if matched_decision else None,
        evidence_card=_dump(evidence_card) if evidence_card else None,
        matched_records={
            "settlement": _dump(settlement) if settlement else None,
            "bank_entry": _dump(bank_entry) if bank_entry else None,
            "ledger_entry": _dump(ledger_entry) if ledger_entry else None,
        },
    )


def fetch_policy_rules(
    rule_ids: list[str],
    context: InvestigationContext,
) -> PolicyRulesResponse:
    """
    Returns business policy rules parameters and descriptions.
    Requires a non-empty context.batch_id; does not evaluate rules.
    """
    if context.batch_id == "":
        raise ValueError("Invalid context: batch_id must not be empty.")

    matched_rules = {}
    for rid in rule_ids:
        if rid in RULES_METADATA:
            matched_rules[rid] = RULES_METADATA[rid]

    return PolicyRulesResponse(rules=matched_rules)


def list_batch_orphans(
    context: InvestigationContext,
) -> BatchOrphansResponse:
    """
    Read-only projection of NormaliserResult orphan/duplicate lists.

    Semantics match backend/app/core/reconciliation/normaliser.py:
      - duplicate bank entries: extra BankEntries sharing a settlement_ref
        (primary = lexicographically smallest bank_entry_id)
      - duplicate ledger entries: extra LedgerEntries sharing a payment_id
        (primary = lexicographically smallest ledger_entry_id)
      - orphan bank entries: settlement_ref not present on any settlement
      - orphan settlements: none of payment_ids exist in the batch
      - orphan ledger entries: payment_id not present in the batch
    """
    if context.batch_id == "":
        raise ValueError("Invalid context: batch_id must not be empty.")

    norm = _normaliser_result(context)
    return BatchOrphansResponse(
        duplicate_bank_entries=[_dump(b) for b in norm.duplicate_bank_entries],
        duplicate_ledger_entries=[_dump(le) for le in norm.duplicate_ledger_entries],
        orphan_bank_entries=[_dump(b) for b in norm.orphan_bank_entries],
        orphan_settlements=[_dump(s) for s in norm.orphan_settlements],
        orphan_ledger_entries=[_dump(le) for le in norm.orphan_ledger_entries],
    )
