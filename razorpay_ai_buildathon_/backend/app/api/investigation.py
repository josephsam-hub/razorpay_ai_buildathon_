"""FastAPI adapter for the bounded agent investigation service."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.schemas import InvestigationRunRequest, InvestigationRunResponse
from app.models.reconciliation_input import ReconciliationBatch
from app.services.investigation import AgentInvestigationResult, AgentInvestigationService

router = APIRouter()

def get_investigation_service() -> AgentInvestigationService:
    return AgentInvestigationService()

@router.post(
    "/investigate",
    response_model=InvestigationRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Investigate one reconciliation exception",
)
def investigate_reconciliation(
    request: InvestigationRunRequest,
    service: AgentInvestigationService = Depends(get_investigation_service),
) -> InvestigationRunResponse:
    """Deserialize the observed batch and delegate investigation orchestration."""
    batch = ReconciliationBatch(
        payments=tuple(request.payments),
        settlements=tuple(request.settlements),
        bank_entries=tuple(request.bank_entries),
        ledger_entries=tuple(request.ledger_entries),
        merchants=tuple(request.merchants),
        batch_id=request.batch_id or "",
    )

    try:
        result: AgentInvestigationResult = service.investigate(
            batch=batch,
            target_payment_id=request.target_payment_id,
            batch_id=request.batch_id or None,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Investigation request failed.",
        ) from error

    return InvestigationRunResponse(
        deterministic_reconciliation=result.reconciliation_result,
        exceptions=result.exceptions,
        investigation_report=result.report,
    )