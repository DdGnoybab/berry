"""FastAPI middleware: cookie → request.state.user_id.

策略:**默认要求登录**,显式声明的路径(PUBLIC_PATHS)放过。
被中间件保护的请求若无 cookie / cookie 无效 / 已过期,直接返 401 JSON。

不在保护范围内的:
  - PUBLIC_PATHS(login / health / methods 列表)
  - 静态资源(由 StaticFiles mount 在 middleware 之外的话不走这里)
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from berry.channels.web.auth.repo import AuthSessionRepo
from berry.channels.web.auth.tokens import hash_token
from berry.core.db.session import async_session_factory

COOKIE_NAME = "berry_session"

PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/auth/login",
        "/health",
        "/v1/methods",
        # Prometheus 容器从 compose 内网抓 /metrics,没有 cookie。
        # 端点本身不暴露公网(nginx 不转发 /metrics),靠网络隔离做边界。
        # 见 spec docs/superpowers/specs/2026-06-15-monitoring-design.md §六。
        "/metrics",
    }
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid session cookie (except PUBLIC_PATHS)."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return _unauthorized()

        token_hash_value = hash_token(token)
        async with async_session_factory() as db:
            row = await AuthSessionRepo(db).get_active(token_hash_value)
        if row is None:
            return _unauthorized()

        request.state.user_id = row.user_id
        return await call_next(request)


def _unauthorized() -> Response:
    return JSONResponse(
        {"error": {"code": "UNAUTHORIZED", "message": "login required"}},
        status_code=401,
    )
