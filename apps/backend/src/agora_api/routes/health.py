"""Health and readiness endpoints."""

from fastapi import APIRouter

from ..config import get_settings

router = APIRouter()


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    """Simple liveness probe."""
    return {"status": "ok"}


@router.get("/readyz")
async def readiness() -> dict[str, str | bool]:
    """Readiness probe – extended over time to check DB, Redis, etc."""
    settings = get_settings()
    return {
        "status": "ok",
        "env": settings.app_env,
        "version": "0.1.0",
    }
