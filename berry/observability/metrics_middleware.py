"""HTTP metric 中间件 + /metrics 端点。

为什么手写而不用 prometheus-fastapi-instrumentator?
  instrumentator(v6 / v7 / v8)的 routing.py 假设所有 starlette route
  都有 `.path` 属性。FastAPI v0.116+ 引入的 `_IncludedRouter` 内部对象
  没有该属性 → 启动后第一个请求 AttributeError 500。
  详见 spec docs/superpowers/specs/2026-06-15-monitoring-design.md 修订记录。

  自己写中间件不依赖 fastapi 内部 route 树,30 行解决,以后 fastapi 升级也不会再炸。

输出 metric:
  http_requests_total{method, handler, status}        Counter
  http_request_duration_seconds{method, handler}      Histogram
  (跟原来 instrumentator 名字一致,Grafana dashboard 不用改)
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from berry.observability.metrics import HTTP_DURATION, HTTP_REQUESTS


class MetricsMiddleware(BaseHTTPMiddleware):
    """记录每个 HTTP 请求的 method / handler / status / duration。

    handler 用 starlette 的 route 模板(如 `/v1/admin/logs/query`),
    不是具体 URL 中的参数,避免高基数。 `/metrics` 端点本身不计入。
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # 自抓不计:/metrics 被 prometheus 容器每 15s 抓一次,
        # 不该污染 http_requests_total。
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        t0 = time.monotonic()
        try:
            response = await call_next(request)
            status = str(response.status_code)
        except Exception:
            # 中间件链上游抛 → 记 500 再 raise。FastAPI 默认 errors handler 也会响应 500。
            HTTP_REQUESTS.labels(method=method, handler=_handler(request), status="500").inc()
            HTTP_DURATION.labels(method=method, handler=_handler(request)).observe(
                time.monotonic() - t0
            )
            raise

        handler = _handler(request)
        HTTP_REQUESTS.labels(method=method, handler=handler, status=status).inc()
        HTTP_DURATION.labels(method=method, handler=handler).observe(time.monotonic() - t0)
        return response


def _handler(request: Request) -> str:
    """从 request.scope 取 route 模板。

    starlette 路由匹配后会把 matched route 放进 scope['route'],
    它有 .path 属性(模板字符串)。降级:用 url.path(可能含动态值,
    但 berry 几乎没动态 URL,问题不大)。
    """
    route = request.scope.get("route")
    if route is not None and hasattr(route, "path"):
        return str(route.path)
    return request.url.path


async def metrics_endpoint(request: Request) -> Response:
    """暴露 prometheus 文本格式 metric。

    Prometheus 容器从 compose 内网抓,公网 nginx 不转发 → 不需鉴权;
    AuthMiddleware 已经把 /metrics 放进 PUBLIC_PATHS。
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
