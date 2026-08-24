"""
LedgerLens — FastAPI application entry point.

Start locally:
    uvicorn app.main:app --reload --port 8000

Docs: http://localhost:8000/docs
Health: http://localhost:8000/health
"""

from fastapi import FastAPI

from app.api.router import api_router
from app.config import settings

app = FastAPI(
    title=settings.app_name,
    description="Evidence-First AI Finance Controller — Razorpay Buildathon Track 04",
    version=settings.api_version,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(api_router)
