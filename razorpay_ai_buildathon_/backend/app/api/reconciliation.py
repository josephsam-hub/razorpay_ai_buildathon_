"""
LedgerLens — Reconciliation Router
==================================
Handles the POST /api/v1/reconciliation/run endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.schemas import ReconciliationRunRequest, ReconciliationRunResponse
from app.models.reconciliation_input import ReconciliationBatch
from app.services.reconciliation import ReconciliationService

router = APIRouter()


@router.post(
    "/run",
    response_model=ReconciliationRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Reconcile a batch of observed financial records",
)
def run_reconciliation(
    request: ReconciliationRunRequest,
    service: ReconciliationService = Depends(),
) -> ReconciliationRunResponse:
    """
    Exposes the deterministic reconciliation engine as an API.
    Accepts lists of Merchants, Payments, Settlements, Bank Entries, and Ledger Entries,
    validates safety boundaries and numeric types, and runs the matching pass.
    """
    # Convert lists of models to tuples to construct ReconciliationBatch safely
    batch = ReconciliationBatch(
        payments=tuple(request.payments),
        settlements=tuple(request.settlements),
        bank_entries=tuple(request.bank_entries),
        ledger_entries=tuple(request.ledger_entries),
        merchants=tuple(request.merchants),
        batch_id=request.batch_id or "",
    )

    try:
        result, exceptions = service.reconcile_batch(batch, batch_id=request.batch_id or None)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal reconciliation failure: {str(e)}",
        )

    return ReconciliationRunResponse(
        reconciliation_result=result,
        exceptions=exceptions,
    )
