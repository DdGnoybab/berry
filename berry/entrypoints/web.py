"""Web entrypoint — starts FastAPI with HTTP RPC + SSE for React frontend.

Run:
  uv run python -m berry.entrypoints.web
"""

from __future__ import annotations

from pathlib import Path

from berry.channels.web.routes import configure_http_rpc
from berry.config import settings
from berry.core.agent.method_registry import MethodRegistry
from berry.entrypoints.cli import (
    _build_runtime,
    _CliTurnRunner,
)
from berry.gateway.methods import register_core
from berry.gateway.methods.turn import configure_runner
from berry.observability.logging import get_logger

logger = get_logger(__name__)

_setup_done = False


def _build_session_cwd_resolver(default_workspace: Path):
    """Resolve session_id → its project's workspace path.

    Lookup walks the filesystem under ``data_root/projects/`` (no DB
    call — runtime needs sync access). Falls back to
    ``default_workspace`` when no matching session dir is found
    (e.g. the very first turn before any session is committed).
    """
    projects_root = settings.data_root / "projects"

    def resolve(session_id: str) -> Path:
        if not projects_root.is_dir():
            return default_workspace
        # data_root/projects/<user_id>/<project_name>/sessions/<session_id>/
        for user_dir in projects_root.iterdir():
            if not user_dir.is_dir():
                continue
            for proj_dir in user_dir.iterdir():
                if not proj_dir.is_dir():
                    continue
                if (proj_dir / "sessions" / session_id).is_dir():
                    return proj_dir
        return default_workspace

    return resolve


async def web_setup() -> None:
    """Wire up the method registry for HTTP transport.

    Called from main.py lifespan, runs in the same event loop as uvicorn.

    Multi-user note: web channel is multi-tenant — there is no startup-time
    user seeding here. Each request reads ``user_id`` from the auth cookie
    (via ``AuthMiddleware``). Admin pre-creates accounts using
    ``berry-cli user create <username>``.
    """
    global _setup_done
    if _setup_done:
        return

    # Fallback workspace for sessions that don't yet exist on disk (plan
    # preview etc.). Not user-specific; lives directly under data_root.
    default_workspace = settings.data_root / "_fallback_workspace"
    default_workspace.mkdir(parents=True, exist_ok=True)
    logger.info(
        "web_default_workspace_resolved", path=str(default_workspace)
    )

    # Dynamic resolver — looks up each session's actual project workspace.
    # Critical for multi-user / multi-project: every session must point at
    # the right project workspace, otherwise file tools collide across
    # tenants.
    cwd_resolver = _build_session_cwd_resolver(default_workspace)

    # Web is multi-user; the system prompt is built once and shared. We
    # intentionally skip the memory index here (user_id=None) — leaking
    # one user's memory file names into another user's prompt would
    # break isolation. Per-turn memory *content* is still loaded via
    # ctx.user_id by ConversationRuntime._load_relevant_memories.
    runtime, system_prompt = _build_runtime(
        cwd_resolver=cwd_resolver, user_id=None
    )
    runner = _CliTurnRunner(runtime, system_prompt, cwd_resolver=cwd_resolver)
    configure_runner(runner)

    registry = MethodRegistry()
    register_core(registry)

    configure_http_rpc(registry)
    _setup_done = True
    logger.info("web_http_rpc_configured")


def main() -> None:
    """Sync entry point: start uvicorn (setup happens in lifespan)."""
    import os

    import uvicorn

    dev = os.environ.get("BERRY_DEV", "").lower() in ("1", "true", "yes")

    uvicorn.run(
        "berry.main:app",
        host="0.0.0.0",
        port=8000,
        reload=dev,
        log_level="info",
    )


if __name__ == "__main__":
    main()
