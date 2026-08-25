"""
Central API router.

Phase 1: health only.
Future phases will add:
  - /api/v1/reconciliation
  - /api/v1/agent
  - /api/v1/audit
  - /api/v1/exceptions
"""

from fastapi import APIRouter

from app.api.health import router as health_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])

# Phase 2+ placeholders:
from app.api.reconciliation import router as reconciliation_router
api_router.include_router(reconciliation_router, prefix="/api/v1/reconciliation", tags=["reconciliation"])
from app.api.investigation import router as investigation_router
api_router.include_router(investigation_router, prefix="/api/v1/reconciliation", tags=["investigation"])
