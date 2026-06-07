"""/health endpoint — service health probe.

Design points:
  - Returns service liveness + Postgres connectivity together.
  - PG-unreachable returns HTTP 503 (so an upstream LB / K8s readiness
    probe can drain traffic).
  - Doesn't leak internal details (no exception messages to clients).
"""

from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from berry import __version__
from berry.core.db.session import engine
from berry.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    service: Literal["ok"]
    postgres: Literal["ok", "down"]


@router.get("/health", response_model=HealthResponse)
async def health() -> JSONResponse:
    """Health check. Returns 503 when PG is unreachable."""
    pg_ok = await _check_postgres()
    payload = HealthResponse(
        status="ok" if pg_ok else "degraded",
        version=__version__,
        service="ok",
        postgres="ok" if pg_ok else "down",
    )
    http_status = (
        status.HTTP_200_OK if pg_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(payload.model_dump(), status_code=http_status)


async def _check_postgres() -> bool:
    """Run a single ``SELECT 1`` to check PG connectivity."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning(
            "health_check_postgres_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return False
