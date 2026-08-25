"""
Shared fixtures for Phase 3.2 evaluation tests.

Fixtures build minimal domain objects in-memory — no file I/O, no DB.
DATABASE_URL env-var workaround mirrors test_health.py pattern.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://ledgerlens:CHANGE_ME@localhost:5432/ledgerlens",
)

from app.data.generator.config import DatasetConfig
from app.data.generator.models import (
    BankEntry, CorruptionEvent, GroundTruth,
    LedgerEntry, Merchant, Payment, Settlement,
)
from app.data.generator.world import ObservedWorld, generate
from app.models.decisions import (
    BatchReconciliationResult, EvidenceCard, MatchEvidence,
    OrphanRecord, ReconciliationDecision, ValidationFinding,
)
from app.models.exceptions import REC_E001, REC_E002, REC_E003, REC_E004, REC_E008, REC_E010
from app.services.reconciliation import ReconciliationService

FIXED_NOW = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Minimal DatasetConfig factories
# ---------------------------------------------------------------------------

def _zero_corruption_config(seed: int = 42, n: int = 20) -> DatasetConfig:
    return DatasetConfig.model_validate({
        "version": "test",
        "n_payments": n,
        "n_merchants": 3,
        "seed": seed,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "corruption": {k: 0.0 for k in [
            "missing_settlement", "missing_bank_entry", "missing_ledger_entry",
            "amount_mismatch", "date_mismatch", "duplicate_bank_entry",
            "settlement_fee_variance", "orphan_bank_entry",
        ]},
    })


def _full_corruption_config(seed: int = 42, n: int = 50) -> DatasetConfig:
    return DatasetConfig.model_validate({
        "version": "test",
        "n_payments": n,
        "n_merchants": 5,
        "seed": seed,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "corruption": {
            "missing_settlement": 0.05,
            "missing_bank_entry": 0.05,
            "missing_ledger_entry": 0.05,
            "amount_mismatch": 0.05,
            "date_mismatch": 0.05,
            "duplicate_bank_entry": 0.03,
            "settlement_fee_variance": 0.03,
            "orphan_bank_entry": 0.02,
        },
    })


# ---------------------------------------------------------------------------
# Tiny hand-crafted ObservedWorld + ReconciliationDecision pairs
# ---------------------------------------------------------------------------

def _make_gt(pid: str, decision: str, corruption_type=None, corruption_code=None) -> GroundTruth:
    return GroundTruth(
        ground_truth_id=f"GT_{pid}",
        payment_id=pid,
        expected_decision=decision,
        discrepancy_type=corruption_type,
        discrepancy_code=corruption_code,
    )


def _make_decision(pid: str, decision: str, codes: list[str] | None = None) -> ReconciliationDecision:
    return ReconciliationDecision(
        payment_id=pid,
        decision=decision,
        confidence=Decimal("1.00") if decision == "AUTO_MATCH" else Decimal("0.80"),
        exception_codes=codes or [],
        audit_id=f"AUD_{pid}",
    )


def _minimal_evidence_card(pid: str, decision: str) -> EvidenceCard:
    ev = MatchEvidence(
        rule_id="R001", rule_description="test", matched=True,
        field_name="settlement_id", score_contribution=Decimal("1.00"),
    )
    return EvidenceCard(
        audit_id=f"AUD_{pid}",
        payment_id=pid,
        decision=decision,
        confidence=Decimal("1.00") if decision == "AUTO_MATCH" else Decimal("0.80"),
        stage_reached="exact" if decision == "AUTO_MATCH" else "composite",
        evidence=[ev],
        validation_findings=[],
        processed_at=FIXED_NOW,
    )


def _make_minimal_observed(
    payments_gt: list[tuple[str, str, str | None, str | None]],
    corruption_events: list[CorruptionEvent] | None = None,
) -> ObservedWorld:
    """
    Build a minimal ObservedWorld from a list of (payment_id, gt_decision,
    corruption_type, corruption_code) tuples.
    """
    gts = [_make_gt(pid, dec, ctype, ccode)
           for pid, dec, ctype, ccode in payments_gt]
    return ObservedWorld(
        merchants=[],
        payments=[],
        settlements=[],
        bank_entries=[],
        ledger_entries=[],
        ground_truth=gts,
        corruption_events=corruption_events or [],
    )


def _make_batch_result(
    decisions: list[ReconciliationDecision],
    orphan_records: list[OrphanRecord] | None = None,
) -> BatchReconciliationResult:
    total = len(decisions)
    n_am = sum(1 for d in decisions if d.decision == "AUTO_MATCH")
    n_hr = sum(1 for d in decisions if d.decision == "HUMAN_REVIEW")
    n_ab = sum(1 for d in decisions if d.decision == "ABSTAIN")
    mr = Decimal(n_am) / Decimal(total) if total > 0 else Decimal("0")
    er = Decimal(n_hr + n_ab) / Decimal(total) if total > 0 else Decimal("0")

    cards = [_minimal_evidence_card(d.payment_id, d.decision) for d in decisions]

    from decimal import ROUND_HALF_UP
    mr = mr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    er = er.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return BatchReconciliationResult(
        batch_id="TEST_BATCH",
        total_records=total,
        auto_matched=n_am,
        human_review=n_hr,
        abstained=n_ab,
        decisions=decisions,
        evidence_cards=cards,
        orphan_records=orphan_records or [],
        match_rate=mr,
        exception_rate=er,
        processed_at=FIXED_NOW,
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def zero_corruption_config():
    return _zero_corruption_config()


@pytest.fixture
def full_corruption_config():
    return _full_corruption_config()


@pytest.fixture
def zero_corruption_world():
    cfg = _zero_corruption_config()
    _clean, observed = generate(cfg)
    return observed


@pytest.fixture
def full_corruption_world():
    cfg = _full_corruption_config()
    _clean, observed = generate(cfg)
    return observed


@pytest.fixture
def recon_service():
    return ReconciliationService()
