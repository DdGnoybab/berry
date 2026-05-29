"""/health 端点 —— 服务健康检查。

设计要点:
- service 自身存活 + Postgres 连通性,两件一起返
- PG 不通时返回 HTTP 503(让上游 LB / K8s readiness probe 摘流量)
- 不返回敏感细节(避免暴露内部信息)
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
    """健康检查。PG 不通时返 503。"""
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
    """跑一次 SELECT 1,看 PG 通不通。"""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        # 不暴露细节给客户端,但内部日志带异常类型 + traceback,便于诊断
        logger.warning(
            "health_check_postgres_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return False
