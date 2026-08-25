"""
LedgerLens Phase 3 — Validation Layer
======================================
Post-match validation of CanonicalTransaction temporal invariants.
Evaluated after structural matching (identity/reference/financial checks).

TIMING INVARIANTS:
  V001 (Settlement Cause)  — settlement_date >= latest_payment_date_in_settlement
  V002 (Settlement Cycle)  — settlement_date == latest_payment_date_in_settlement + settlement_cycle_days
  V003 (Bank Timing)       — 0 <= value_date - settlement_date <= 1 day
  V004 (Ledger Timing)     — 0 <= posting_date - value_date <= 2 days

DETERMINISM:
  All dates are compared using python datetime.date objects.
  Outputs are fully deterministic and candidate-specific.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from app.models.canonical import CanonicalTransaction
from app.models.decisions import ValidationFinding
from app.models.exceptions import REC_E004
from app.core.reconciliation.policy import (
    V003_MAX_DAYS_AFTER_SETTLEMENT,
    V004_MAX_DAYS_AFTER_VALUE,
)


def run_validation(ct: CanonicalTransaction) -> list[ValidationFinding]:
    """
    Run post-match validation rules against a CanonicalTransaction.
    Only validates fields for candidate records that are present (candidate-specific).
    """
    findings: list[ValidationFinding] = []

    # ------------------------------------------------------------------
    # V001 — Settlement Cause (settlement_date >= latest_payment_date_in_settlement)
    # ------------------------------------------------------------------
    if ct.has_settlement and ct.latest_payment_date_in_settlement is not None:
        passed_v001 = ct.settlement_date >= ct.latest_payment_date_in_settlement
        delta_v001 = (ct.settlement_date - ct.latest_payment_date_in_settlement).days
        findings.append(
            ValidationFinding(
                rule_id="V001",
                rule_description="Settlement date must be on or after the latest payment date in the settlement batch.",
                passed=passed_v001,
                severity="ERROR",
                expected_relationship=f"settlement_date >= {ct.latest_payment_date_in_settlement}",
                observed_relationship=f"settlement_date = {ct.settlement_date}",
                delta=f"{delta_v001:+d} days",
                affected_record_ids=[ct.payment_id, ct.settlement_id],
                discrepancy_code=REC_E004 if not passed_v001 else None,
            )
        )

    # ------------------------------------------------------------------
    # V002 — Settlement Cycle (settlement_date == latest_payment_date_in_settlement + settlement_cycle_days)
    # ------------------------------------------------------------------
    if (
        ct.has_settlement
        and ct.latest_payment_date_in_settlement is not None
        and ct.settlement_cycle_days is not None
    ):
        expected_settlement_date = ct.latest_payment_date_in_settlement + timedelta(
            days=ct.settlement_cycle_days
        )
        passed_v002 = ct.settlement_date == expected_settlement_date
        delta_v002 = (ct.settlement_date - expected_settlement_date).days
        findings.append(
            ValidationFinding(
                rule_id="V002",
                rule_description="Settlement date must match the expected merchant cycle delay after the latest payment date.",
                passed=passed_v002,
                severity="WARNING",
                expected_relationship=(
                    f"settlement_date == {ct.latest_payment_date_in_settlement} "
                    f"+ {ct.settlement_cycle_days} days ({expected_settlement_date})"
                ),
                observed_relationship=f"settlement_date = {ct.settlement_date}",
                delta=f"{delta_v002:+d} days",
                affected_record_ids=[ct.payment_id, ct.settlement_id],
                discrepancy_code=REC_E004 if not passed_v002 else None,
            )
        )

    # ------------------------------------------------------------------
    # V003 — Bank Timing (0 <= value_date - settlement_date <= 1)
    # ------------------------------------------------------------------
    if ct.has_settlement and ct.has_bank_entry and ct.value_date is not None:
        delta_v003 = (ct.value_date - ct.settlement_date).days
        passed_v003 = 0 <= delta_v003 <= V003_MAX_DAYS_AFTER_SETTLEMENT
        findings.append(
            ValidationFinding(
                rule_id="V003",
                rule_description=(
                    f"Bank entry value date must be within 0 to "
                    f"{V003_MAX_DAYS_AFTER_SETTLEMENT} days after the settlement date."
                ),
                passed=passed_v003,
                severity="ERROR",
                expected_relationship=(
                    f"0 <= value_date - settlement_date ({ct.settlement_date}) "
                    f"<= {V003_MAX_DAYS_AFTER_SETTLEMENT}"
                ),
                observed_relationship=f"value_date = {ct.value_date}",
                delta=f"{delta_v003:+d} days",
                affected_record_ids=[ct.settlement_id, ct.bank_entry_id],
                discrepancy_code=REC_E004 if not passed_v003 else None,
            )
        )

    # ------------------------------------------------------------------
    # V004 — Ledger Timing (0 <= posting_date - value_date <= 2)
    # ------------------------------------------------------------------
    if ct.has_bank_entry and ct.has_ledger_entry and ct.posting_date is not None:
        delta_v004 = (ct.posting_date - ct.value_date).days
        passed_v004 = 0 <= delta_v004 <= V004_MAX_DAYS_AFTER_VALUE
        findings.append(
            ValidationFinding(
                rule_id="V004",
                rule_description=(
                    f"Ledger posting date must be within 0 to "
                    f"{V004_MAX_DAYS_AFTER_VALUE} days after the bank entry value date."
                ),
                passed=passed_v004,
                severity="ERROR",
                expected_relationship=(
                    f"0 <= posting_date - value_date ({ct.value_date}) "
                    f"<= {V004_MAX_DAYS_AFTER_VALUE}"
                ),
                observed_relationship=f"posting_date = {ct.posting_date}",
                delta=f"{delta_v004:+d} days",
                affected_record_ids=[ct.bank_entry_id, ct.ledger_entry_id],
                discrepancy_code=REC_E004 if not passed_v004 else None,
            )
        )

    return findings
