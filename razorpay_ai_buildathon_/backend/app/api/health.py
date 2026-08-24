"""
Health endpoint — GET /health

Returns service liveness status.
Used by load balancers, CI checks, and local verification.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.api_version,
    )
