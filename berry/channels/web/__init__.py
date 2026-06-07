"""Web channel — HTTP/SSE transport.

User-facing:
  - POST /v1/rpc           — one-shot RPC method call
  - POST /v1/turn/stream   — SSE streaming turn.send + suggestion events
  - GET  /v1/methods       — registered method discovery
  - GET  /health           — service health probe
  - REST under /v1/...     — project / session / etc. (unchanged)

Internal layout:
  - routes.py       — FastAPI router + endpoints
  - sse_adapter.py  — subscribe to EventBus, translate to SSE frames
  - health.py       — service health probe
"""

from berry.channels.web.routes import configure_http_rpc, router

__all__ = ["configure_http_rpc", "router"]
