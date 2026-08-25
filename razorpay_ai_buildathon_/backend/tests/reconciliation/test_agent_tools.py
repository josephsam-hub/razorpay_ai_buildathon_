"""
LedgerLens — Agent Tools and Gemini Client Tests (Phase 4 P4-1 & P4-2)
======================================================================
Tests config overrides, client fallback, scope controls, and read-only tools.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from app.config import settings
from app.services.gemini import GeminiClient, GeminiUnavailableError
from app.models.investigation import InvestigationContext, InvestigationReport
from app.models.reconciliation_input import from_observed_world
from app.services.tools import (
    fetch_payment_evidence,
    fetch_policy_rules,
    list_batch_orphans,
)
from tests.reconciliation.conftest import (
    make_clean_world,
    make_merchant,
    make_payment,
    make_settlement,
    make_bank_entry,
    make_ledger_entry,
)
from app.services.reconciliation import ReconciliationService

# ── P4-1: Gemini Client Configuration Tests ──────────────────────────────────

def test_missing_gemini_configuration() -> None:
    client = GeminiClient(api_key=None)
    with pytest.raises(GeminiUnavailableError) as exc_info:
        client.get_client()
    assert "API key is not configured" in str(exc_info.value)


def test_invalid_gemini_configuration() -> None:
    client = GeminiClient(api_key="dummy_key", model="non-existent-model", sleeper=lambda _s: None)

    def _fail(*_args, **_kwargs):
        raise RuntimeError("model not found")

    client._invoke_generate = _fail  # type: ignore[method-assign]
    with pytest.raises(GeminiUnavailableError) as exc_info:
        from pydantic import BaseModel
        class FakeSchema(BaseModel):
            value: str
        client.generate_structured_content("hello", FakeSchema)
    assert "Gemini API request failed" in str(exc_info.value)


def test_timeout_configuration() -> None:
    client = GeminiClient(api_key="dummy_key", timeout_seconds=1, sleeper=lambda _s: None)
    assert client.timeout == 1

    def _timeout(*_args, **_kwargs):
        raise TimeoutError("deadline exceeded")

    client._invoke_generate = _timeout  # type: ignore[method-assign]
    with pytest.raises(GeminiUnavailableError) as exc_info:
        from pydantic import BaseModel
        class FakeSchema(BaseModel):
            value: str
        client.generate_structured_content("hello", FakeSchema)
    assert "Gemini API request failed" in str(exc_info.value)


def test_deterministic_behavior_when_gemini_unavailable() -> None:
    client = GeminiClient(api_key=None)
    with pytest.raises(GeminiUnavailableError):
        from pydantic import BaseModel
        class FakeSchema(BaseModel):
            value: str
        client.generate_structured_content("hello", FakeSchema)


# ── P4-2: InvestigationContext & Tool Scope Tests ─────────────────────────────

def test_empty_investigation_context() -> None:
    from app.models.decisions import BatchReconciliationResult

    batch = from_observed_world(make_clean_world())
    reconciliation_result = BatchReconciliationResult(
        batch_id="TEST",
        total_records=0,
        auto_matched=0,
        human_review=0,
        abstained=0,
        match_rate=Decimal("0.00"),
        exception_rate=Decimal("0.00"),
        decisions=[],
        evidence_cards=[],
        processed_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ValueError):
        context = InvestigationContext(
            batch_id="",
            target_payment_id="PAY_1",
            reconciliation_result=reconciliation_result,
            batch=batch,
            allowed_payment_ids=set(),
        )
        list_batch_orphans(context)


def test_cross_batch_access_rejection() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id

    context = InvestigationContext(
        batch_id="BATCH_A",
        target_payment_id=target_id,
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={target_id},
    )

    res = fetch_payment_evidence(target_id, context)
    assert res.payment["payment_id"] == target_id

    with pytest.raises(ValueError) as exc_info:
        fetch_payment_evidence("PAY_EXTERNAL", context)
    assert "Access denied: Payment ID outside allowed context scope" in str(exc_info.value)


def test_invalid_payment_id() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")

    context = InvestigationContext(
        batch_id="BATCH_A",
        target_payment_id="PAY_NONEXISTENT",
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={"PAY_NONEXISTENT"},
    )

    with pytest.raises(ValueError) as exc_info:
        fetch_payment_evidence("PAY_NONEXISTENT", context)
    assert "Payment ID not found in current batch" in str(exc_info.value)


def test_ground_truth_isolation() -> None:
    observed = make_clean_world()
    assert hasattr(observed, "ground_truth")

    batch = from_observed_world(observed)
    assert not hasattr(batch, "ground_truth")

    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id

    context = InvestigationContext(
        batch_id="BATCH_A",
        target_payment_id=target_id,
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={target_id},
    )

    evidence_res = fetch_payment_evidence(target_id, context).model_dump()
    assert "ground_truth" not in evidence_res
    assert "ground_truth" not in evidence_res["payment"]
    for record in evidence_res["matched_records"].values():
        if record:
            assert "ground_truth" not in record

    orphan_res = list_batch_orphans(context).model_dump()
    for category in orphan_res.values():
        for item in category:
            assert "ground_truth" not in item


def test_corruption_event_isolation() -> None:
    observed = make_clean_world()
    assert hasattr(observed, "corruption_events")

    batch = from_observed_world(observed)
    assert not hasattr(batch, "corruption_events")

    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id

    context = InvestigationContext(
        batch_id="BATCH_A",
        target_payment_id=target_id,
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={target_id},
    )

    evidence_res = fetch_payment_evidence(target_id, context).model_dump()
    assert "corruption_events" not in evidence_res
    assert "corruption_events" not in evidence_res["payment"]
    assert "corruption_id" not in evidence_res["payment"]
    assert "original_value" not in evidence_res["payment"]
    assert "applied_seed" not in evidence_res["payment"]

    orphan_res = list_batch_orphans(context).model_dump()
    for category in orphan_res.values():
        for item in category:
            assert "corruption_events" not in item
            assert "corruption_id" not in item
            assert "applied_seed" not in item


# ── P4-3: Adversarial Validation and Hardening Tests ─────────────────────────

def test_context_and_batch_immutability() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id

    context = InvestigationContext(
        batch_id="BATCH_A",
        target_payment_id=target_id,
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={target_id},
    )

    # 1. Attempting to modify fields on frozen Pydantic InvestigationContext raises ValidationError
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        context.batch_id = "BATCH_B"

    # 2. Attempting to modify fields on frozen ReconciliationBatch dataclass raises FrozenInstanceError (AttributeError in python)
    with pytest.raises(AttributeError):
        context.batch.payments = ()

    assert isinstance(context.allowed_payment_ids, frozenset)
    with pytest.raises(AttributeError):
        context.allowed_payment_ids.add("PAY_OUTSIDE_SCOPE")


def test_empty_or_whitespace_context_rejection() -> None:
    from pydantic import ValidationError
    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")

    # Reject empty string batch_id
    with pytest.raises(ValidationError):
        InvestigationContext(
            batch_id="",
            target_payment_id="PAY_1",
            reconciliation_result=result,
            batch=batch,
            allowed_payment_ids=set(),
        )

    # Reject whitespace-only target_payment_id
    with pytest.raises(ValidationError):
        InvestigationContext(
            batch_id="BATCH_A",
            target_payment_id="   ",
            reconciliation_result=result,
            batch=batch,
            allowed_payment_ids=set(),
        )


def test_unknown_policy_rule_ids_handling() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id

    context = InvestigationContext(
        batch_id="BATCH_A",
        target_payment_id=target_id,
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={target_id},
    )

    # Query rule IDs that do not exist
    res = fetch_policy_rules(["R999", "INVALID_RULE"], context)
    assert isinstance(res.rules, dict)
    assert len(res.rules) == 0  # Safely returns empty dict without throwing errors


def test_exact_decimal_precision_preserved() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id

    context = InvestigationContext(
        batch_id="BATCH_A",
        target_payment_id=target_id,
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={target_id},
    )

    res = fetch_payment_evidence(target_id, context)
    # Check amount is serialised as exact decimal compatible string representation
    assert res.payment["amount"] == "5000.00"
    assert isinstance(res.payment["amount"], str)


def test_credential_redaction_in_exceptions() -> None:
    secret_key = "MY_SUPER_SECRET_GEMINI_KEY_12345"
    client = GeminiClient(api_key=secret_key, model="invalid-model", sleeper=lambda _s: None)

    # 1. Test manual redaction helper
    assert client._redact(f"failed with {secret_key}") == "failed with [REDACTED_API_KEY]"

    def _leak(*_args, **_kwargs):
        raise RuntimeError(f"provider rejected key {secret_key}")

    client._invoke_generate = _leak  # type: ignore[method-assign]
    with pytest.raises(GeminiUnavailableError) as exc_info:
        from pydantic import BaseModel
        class Dummy(BaseModel):
            v: str
        client.generate_structured_content("hi", Dummy)

    error_msg = str(exc_info.value)
    assert secret_key not in error_msg


def test_tools_never_call_gemini() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id

    context = InvestigationContext(
        batch_id="BATCH_A",
        target_payment_id=target_id,
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={target_id},
    )

    # Calling tools works perfectly without needing a configured API key or importing SDK Client
    rules_res = fetch_policy_rules(["R001"], context)
    assert "R001" in rules_res.rules

    orphans_res = list_batch_orphans(context)
    assert isinstance(orphans_res.orphan_bank_entries, list)


def test_spoofed_batch_id_isolation() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id

    # Spoof context's batch_id to something else
    context = InvestigationContext(
        batch_id="BATCH_SPOOFED_XY",
        target_payment_id=target_id,
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={target_id},
    )

    # The tool returns evidence *only* from the current batch payload bound to the context.
    # It cannot reach any other batch dataset.
    res = fetch_payment_evidence(target_id, context)
    assert res.payment["payment_id"] == target_id


# ── P4-4: Structured InvestigationReport Schema Tests ────────────────────────

def test_invalid_confidence_values() -> None:
    from pydantic import ValidationError

    # Reconciliation confidence < 0
    with pytest.raises(ValidationError) as exc_info:
        InvestigationReport(
            payment_id="PAY_1",
            batch_id="BATCH_1",
            status="AVAILABLE",
            reconciliation_confidence=Decimal("-0.10"),
            investigation_confidence=Decimal("0.50"),
        )
    assert "Reconciliation confidence must be in range" in str(exc_info.value)

    # Reconciliation confidence > 1
    with pytest.raises(ValidationError) as exc_info:
        InvestigationReport(
            payment_id="PAY_1",
            batch_id="BATCH_1",
            status="AVAILABLE",
            reconciliation_confidence=Decimal("1.50"),
            investigation_confidence=Decimal("0.50"),
        )
    assert "Reconciliation confidence must be in range" in str(exc_info.value)

    # Investigation confidence > 1
    with pytest.raises(ValidationError) as exc_info:
        InvestigationReport(
            payment_id="PAY_1",
            batch_id="BATCH_1",
            status="AVAILABLE",
            reconciliation_confidence=Decimal("0.80"),
            investigation_confidence=Decimal("1.02"),
        )
    assert "Investigation confidence must be in range" in str(exc_info.value)


def test_missing_required_fields() -> None:
    from pydantic import ValidationError

    # Missing status
    with pytest.raises(ValidationError):
        InvestigationReport(
            payment_id="PAY_1",
            batch_id="BATCH_1",
            reconciliation_confidence=Decimal("0.90"),
        )


def test_reconciliation_result_preservation_on_fallback() -> None:
    from app.models.investigation import InvestigationReport

    # Simulate Gemini failure fallback construction
    report = InvestigationReport.build_fallback(
        batch_id="BATCH_A",
        payment_id="PAY_123",
        reconciliation_confidence=Decimal("0.75"),
        status="UNAVAILABLE",
        error_message="Connection timed out after 3000ms"
    )

    # Verify that status is UNAVAILABLE, and reconciliation confidence remains AUTHORITATIVE
    assert report.status == "UNAVAILABLE"
    assert report.reconciliation_confidence == Decimal("0.75")
    assert report.payment_id == "PAY_123"
    assert report.batch_id == "BATCH_A"
    assert "Connection timed out" in report.agent_explanation
    assert report.investigation_confidence is None
    assert report.root_cause is None
    assert len(report.violated_rules) == 0


def test_hallucination_prevention_traceability() -> None:
    # Verifies that any constructed report maps strictly back to the original identifiers
    from app.models.investigation import InvestigationReport

    report = InvestigationReport(
        payment_id="PAY_MATCHED_ACTUAL",
        batch_id="BATCH_A",
        status="AVAILABLE",
        reconciliation_confidence=Decimal("1.00"),
        investigation_confidence=Decimal("1.00"),
        agent_explanation="Deterministic trace complete.",
        suggested_actions=["None"],
        root_cause="AMOUNT_MISMATCH",
        violated_rules=["R001"],
    )

    # Assert exact traceability variables match construction fields
    assert report.payment_id == "PAY_MATCHED_ACTUAL"
    assert report.reconciliation_confidence == Decimal("1.00")
    assert report.violated_rules == ["R001"]


def test_confidence_nan_and_infinity_rejected() -> None:
    from pydantic import ValidationError

    # Reconciliation confidence = NaN
    with pytest.raises(ValidationError) as exc_info:
        InvestigationReport(
            payment_id="PAY_1",
            batch_id="BATCH_1",
            status="AVAILABLE",
            reconciliation_confidence=Decimal("NaN"),
        )
    assert "finite number" in str(exc_info.value) or "cannot be NaN or Infinity" in str(exc_info.value)

    # Investigation confidence = Infinity
    with pytest.raises(ValidationError) as exc_info:
        InvestigationReport(
            payment_id="PAY_1",
            batch_id="BATCH_1",
            status="AVAILABLE",
            reconciliation_confidence=Decimal("0.90"),
            investigation_confidence=Decimal("Infinity"),
        )
    assert "finite number" in str(exc_info.value) or "cannot be NaN or Infinity" in str(exc_info.value)


# ── Hardening: Gemini retry / error policy ───────────────────────────────────

def test_missing_api_key_is_not_retried() -> None:
    from pydantic import BaseModel

    sleeps: list[float] = []
    client = GeminiClient(api_key=None, max_retries=3, sleeper=lambda s: sleeps.append(s))

    class FakeSchema(BaseModel):
        value: str

    with pytest.raises(GeminiUnavailableError) as exc_info:
        client.generate_structured_content("hello", FakeSchema)
    assert "API key is not configured" in str(exc_info.value)
    assert sleeps == []


def test_transient_errors_are_retried_then_succeed() -> None:
    from pydantic import BaseModel

    sleeps: list[float] = []
    client = GeminiClient(api_key="k", max_retries=3, sleeper=lambda s: sleeps.append(s))
    calls = {"n": 0}

    class FakeSchema(BaseModel):
        value: str

    def _flaky(_prompt, _schema, _system=None) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("deadline exceeded")
        return FakeSchema(value="ok").model_dump_json()

    client._invoke_generate = _flaky  # type: ignore[method-assign]
    result = client.generate_structured_content("hello", FakeSchema)
    assert result.value == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_malformed_json_is_not_retried() -> None:
    from pydantic import BaseModel

    sleeps: list[float] = []
    client = GeminiClient(api_key="k", max_retries=5, sleeper=lambda s: sleeps.append(s))
    calls = {"n": 0}

    class FakeSchema(BaseModel):
        value: str

    def _bad(_prompt, _schema, _system=None) -> str:
        calls["n"] += 1
        return "not-json{"

    client._invoke_generate = _bad  # type: ignore[method-assign]
    with pytest.raises(GeminiUnavailableError):
        client.generate_structured_content("hello", FakeSchema)
    assert calls["n"] == 1
    assert sleeps == []


def test_permanent_provider_error_is_not_retried() -> None:
    from pydantic import BaseModel

    sleeps: list[float] = []
    client = GeminiClient(api_key="k", max_retries=4, sleeper=lambda s: sleeps.append(s))
    calls = {"n": 0}

    class FakeSchema(BaseModel):
        value: str

    def _perm(_prompt, _schema, _system=None) -> str:
        calls["n"] += 1
        raise RuntimeError("PERMISSION_DENIED: model disabled")

    client._invoke_generate = _perm  # type: ignore[method-assign]
    with pytest.raises(GeminiUnavailableError):
        client.generate_structured_content("hello", FakeSchema)
    assert calls["n"] == 1
    assert sleeps == []


def test_gemini_failure_does_not_mutate_reconciliation_result() -> None:
    from pydantic import BaseModel

    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, exceptions = service.reconcile_batch(batch, batch_id="BATCH_A")
    snapshot = result.model_dump()

    client = GeminiClient(api_key=None)

    class FakeSchema(BaseModel):
        value: str

    with pytest.raises(GeminiUnavailableError):
        client.generate_structured_content("hello", FakeSchema)

    assert result.model_dump() == snapshot
    assert isinstance(exceptions, list)


# ── Hardening: list_batch_orphans uses normaliser semantics ───────────────────

def _context_for(batch, result, target_id: str, batch_id: str = "BATCH_A") -> InvestigationContext:
    return InvestigationContext(
        batch_id=batch_id,
        target_payment_id=target_id,
        reconciliation_result=result,
        batch=batch,
        allowed_payment_ids={p.payment_id for p in batch.payments} | {target_id},
    )


def test_list_batch_orphans_matches_normaliser_duplicates_and_orphans() -> None:
    from app.core.reconciliation.normaliser import normalise
    from app.data.generator.world import ObservedWorld

    m = make_merchant()
    p = make_payment()
    s = make_settlement(payment_ids=["PAY_20260801_00001"])
    primary_bank = make_bank_entry(bid="BNK_20260802_0001")
    duplicate_bank = make_bank_entry(bid="BNK_20260802_0002")
    orphan_bank = make_bank_entry(bid="BNK_ORPHAN_0001", settlement_ref="REF_ORPHAN_99999")
    primary_ledger = make_ledger_entry(lid="LED_20260802_0001")
    duplicate_ledger = make_ledger_entry(lid="LED_20260802_0002", allocated="100.00")
    orphan_ledger = make_ledger_entry(lid="LED_ORPHAN_0001", payment_id="PAY_UNKNOWN_00099")
    orphan_settlement = make_settlement(
        "SET_ORPHAN_9999",
        payment_ids=["PAY_UNKNOWN_00099"],
        settlement_ref="REF_ORPHAN_SET",
        gross="1000.00",
        fee="20.00",
        net="980.00",
    )
    world = ObservedWorld(
        merchants=[m],
        payments=[p],
        settlements=[s, orphan_settlement],
        bank_entries=[primary_bank, duplicate_bank, orphan_bank],
        ledger_entries=[primary_ledger, duplicate_ledger, orphan_ledger],
        ground_truth=[],
        corruption_events=[],
    )
    batch = from_observed_world(world)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    context = _context_for(batch, result, p.payment_id)

    tool = list_batch_orphans(context)
    norm = normalise(batch)

    assert [row["bank_entry_id"] for row in tool.duplicate_bank_entries] == [
        b.bank_entry_id for b in norm.duplicate_bank_entries
    ]
    assert [row["ledger_entry_id"] for row in tool.duplicate_ledger_entries] == [
        le.ledger_entry_id for le in norm.duplicate_ledger_entries
    ]
    assert [row["bank_entry_id"] for row in tool.orphan_bank_entries] == [
        b.bank_entry_id for b in norm.orphan_bank_entries
    ]
    assert [row["settlement_id"] for row in tool.orphan_settlements] == [
        st.settlement_id for st in norm.orphan_settlements
    ]
    assert [row["ledger_entry_id"] for row in tool.orphan_ledger_entries] == [
        le.ledger_entry_id for le in norm.orphan_ledger_entries
    ]
    assert "BNK_20260802_0002" in {row["bank_entry_id"] for row in tool.duplicate_bank_entries}
    assert "BNK_20260802_0002" not in {row["bank_entry_id"] for row in tool.orphan_bank_entries}
    assert "LED_20260802_0002" in {row["ledger_entry_id"] for row in tool.duplicate_ledger_entries}
    assert "LED_20260802_0001" not in {row["ledger_entry_id"] for row in tool.duplicate_ledger_entries}


def test_unmatched_linked_bank_is_not_reported_as_orphan() -> None:
    from app.core.reconciliation.normaliser import normalise

    observed = make_clean_world()
    batch = from_observed_world(observed)
    service = ReconciliationService()
    result, _ = service.reconcile_batch(batch, batch_id="BATCH_A")
    context = _context_for(batch, result, batch.payments[0].payment_id)
    tool = list_batch_orphans(context)
    norm = normalise(batch)
    assert tool.orphan_bank_entries == []
    assert norm.orphan_bank_entries == []


def test_duplicate_ledgers_are_not_grouped_by_amount() -> None:
    from app.data.generator.world import ObservedWorld

    m = make_merchant()
    p1 = make_payment("PAY_20260801_00001")
    p2 = make_payment("PAY_20260801_00002")
    s1 = make_settlement("SET_20260802_0001", payment_ids=["PAY_20260801_00001"], settlement_ref="REF_A")
    s2 = make_settlement(
        "SET_20260802_0002",
        payment_ids=["PAY_20260801_00002"],
        settlement_ref="REF_B",
        gross="5000.00",
        fee="100.00",
        net="4900.00",
    )
    le1 = make_ledger_entry(lid="LED_A", payment_id="PAY_20260801_00001", settlement_id="SET_20260802_0001")
    le2 = make_ledger_entry(lid="LED_B", payment_id="PAY_20260801_00002", settlement_id="SET_20260802_0002")
    world = ObservedWorld(
        merchants=[m],
        payments=[p1, p2],
        settlements=[s1, s2],
        bank_entries=[],
        ledger_entries=[le1, le2],
        ground_truth=[],
        corruption_events=[],
    )
    batch = from_observed_world(world)
    result, _ = ReconciliationService().reconcile_batch(batch, batch_id="BATCH_A")
    context = _context_for(batch, result, p1.payment_id)
    tool = list_batch_orphans(context)
    assert tool.duplicate_ledger_entries == []


# ── Hardening: RULES_METADATA accuracy ───────────────────────────────────────

def test_rules_metadata_r001_is_settlement_presence() -> None:
    from app.services.tools import RULES_METADATA

    observed = make_clean_world()
    batch = from_observed_world(observed)
    result, _ = ReconciliationService().reconcile_batch(batch, batch_id="BATCH_A")
    context = _context_for(batch, result, batch.payments[0].payment_id)
    res = fetch_policy_rules(["R001"], context)
    assert "Gross Amount" not in res.rules["R001"]["description"]
    assert "Settlement record exists" in res.rules["R001"]["description"]
    assert RULES_METADATA["R001"]["category"] == "exact"


def test_rules_metadata_does_not_imply_removed_r012_window() -> None:
    from app.services.tools import RULES_METADATA
    from app.core.reconciliation.policy import SETTLEMENT_DATE_MAX_DAYS_AFTER_PAYMENT

    assert "R012" not in RULES_METADATA
    v001_params = RULES_METADATA["V001"]["parameters"]
    assert "max_lag_days" not in v001_params
    assert SETTLEMENT_DATE_MAX_DAYS_AFTER_PAYMENT not in v001_params.values()
    assert "exact cycle match" in RULES_METADATA["V002"]["description"]


def test_rules_metadata_v003_v004_parameters_match_policy() -> None:
    from app.services.tools import RULES_METADATA
    from app.core.reconciliation.policy import (
        V003_MAX_DAYS_AFTER_SETTLEMENT,
        V004_MAX_DAYS_AFTER_VALUE,
        CS004_MAX_DATE_DISTANCE_DAYS,
    )

    assert RULES_METADATA["V003"]["parameters"]["max_days_after_settlement"] == V003_MAX_DAYS_AFTER_SETTLEMENT
    assert RULES_METADATA["V004"]["parameters"]["max_days_after_value"] == V004_MAX_DAYS_AFTER_VALUE
    assert RULES_METADATA["CS004"]["parameters"]["max_date_distance_days"] == CS004_MAX_DATE_DISTANCE_DAYS
    assert "never produces AUTO_MATCH" in RULES_METADATA["CS003"]["description"]


# ── Hardening: InvestigationReport cannot override reconciliation ─────────────

def test_from_llm_output_ignores_hallucinated_identity_and_amounts() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    result, _ = ReconciliationService().reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id
    engine_confidence = next(d.confidence for d in result.decisions if d.payment_id == target_id)
    context = _context_for(batch, result, target_id)

    report = InvestigationReport.from_llm_output(
        context,
        {
            "payment_id": "PAY_HALLUCINATED",
            "batch_id": "BATCH_OTHER",
            "reconciliation_confidence": "0.01",
            "investigation_confidence": "0.40",
            "amount": "999999.99",
            "exception_codes": ["rec:E999", "rec:E002"],
            "agent_explanation": "invented cash gap",
            "suggested_actions": ["do nothing"],
            "root_cause": "AMOUNT_MISMATCH",
            "violated_rules": ["R010", "rec:E002", "R999"],
        },
    )
    assert report.status == "AVAILABLE"
    assert report.payment_id == target_id
    assert report.batch_id == "BATCH_A"
    assert report.reconciliation_confidence == engine_confidence
    assert report.investigation_confidence == Decimal("0.40")
    assert "amount" not in report.model_dump()
    assert "exception_codes" not in InvestigationReport.model_fields
    assert "rec:E002" not in report.violated_rules
    assert "R999" not in report.violated_rules
    if "R010" in report.violated_rules:
        card = next(c for c in result.evidence_cards if c.payment_id == target_id)
        assert "R010" in card.rules_triggered or any(
            f.rule_id == "R010" and not f.passed for f in card.validation_findings
        )


def test_from_llm_output_rejects_malformed_payload_and_preserves_confidence() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    result, _ = ReconciliationService().reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id
    engine_confidence = next(d.confidence for d in result.decisions if d.payment_id == target_id)
    snapshot = result.model_dump()
    context = _context_for(batch, result, target_id)

    report = InvestigationReport.from_llm_output(context, "not-a-dict")
    assert report.status == "INVALID_OUTPUT"
    assert report.payment_id == target_id
    assert report.reconciliation_confidence == engine_confidence
    assert report.investigation_confidence is None
    assert result.model_dump() == snapshot


def test_from_llm_output_rejects_nan_investigation_confidence() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    result, _ = ReconciliationService().reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id
    engine_confidence = next(d.confidence for d in result.decisions if d.payment_id == target_id)
    context = _context_for(batch, result, target_id)

    report = InvestigationReport.from_llm_output(
        context,
        {"investigation_confidence": "NaN", "agent_explanation": "x"},
    )
    assert report.status == "INVALID_OUTPUT"
    assert report.reconciliation_confidence == engine_confidence
    assert report.investigation_confidence is None


def test_from_llm_output_rejects_unknown_root_cause() -> None:
    observed = make_clean_world()
    batch = from_observed_world(observed)
    result, _ = ReconciliationService().reconcile_batch(batch, batch_id="BATCH_A")
    target_id = batch.payments[0].payment_id
    context = _context_for(batch, result, target_id)
    report = InvestigationReport.from_llm_output(
        context,
        {"root_cause": "ENGINE_OVERRIDE", "investigation_confidence": "0.9"},
    )
    assert report.status == "INVALID_OUTPUT"
    assert report.root_cause is None
