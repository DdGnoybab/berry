"""Web entrypoint — starts FastAPI with HTTP RPC + SSE for React frontend.

Run:
  uv run python -m berry.entrypoints.web
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from berry.config import settings
from berry.core.db.repos.project_repo import ProjectRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.core.db.session import async_session_factory
from berry.core.project.service import ProjectService
from berry.entrypoints.cli import (
    DEMO_PROJECT_NAME,
    DEFAULT_USER_HANDLE,
    _build_runtime,
    _CliTurnRunner,
)
from berry.gateway.http.rpc import configure_http_rpc
from berry.gateway.methods import register_core
from berry.gateway.methods.registry import MethodRegistry
from berry.gateway.methods.turn import configure_runner
from berry.observability.logging import configure_logging, get_logger

logger = get_logger(__name__)

_setup_done = False


async def _seed_user() -> UUID:
    async with async_session_factory() as db:
        user = await UserRepo(db).get_or_create_by_handle(
            handle=DEFAULT_USER_HANDLE,
            display_name="Default User",
        )
        return user.id


async def _ensure_demo_project(user_id: UUID) -> UUID:
    async with async_session_factory() as db:
        repo = ProjectRepo(db)
        existing = await repo.get_by_user_and_name(user_id, DEMO_PROJECT_NAME)
        if existing is not None:
            return existing.id

    async with async_session_factory() as db:
        repo = ProjectRepo(db)
        svc = ProjectService(settings.data_root)
        ws_path = svc.workspace_relative_path(user_id, DEMO_PROJECT_NAME)
        project = await repo.create(
            user_id=user_id,
            name=DEMO_PROJECT_NAME,
            title="Web Demo",
            domain="general",
            workspace_path=ws_path,
        )
        svc.init_workspace(project)
        return project.id


async def web_setup() -> None:
    """Wire up the method registry for HTTP transport.

    Called from main.py lifespan, runs in the same event loop as uvicorn.
    """
    global _setup_done
    if _setup_done:
        return

    user_id = await _seed_user()
    logger.info("web_user_seeded", user_id=str(user_id))

    project_id = await _ensure_demo_project(user_id)
    logger.info("web_project_ready", project_id=str(project_id))

    runtime, system_prompt = _build_runtime()
    runner = _CliTurnRunner(runtime, system_prompt)
    configure_runner(runner)

    registry = MethodRegistry()
    register_core(registry)

    configure_http_rpc(registry, user_id)
    _setup_done = True
    logger.info("web_http_rpc_configured")


def main() -> None:
    """Sync entry point: start uvicorn (setup happens in lifespan)."""
    import uvicorn

    uvicorn.run(
        "berry.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
