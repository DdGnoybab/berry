"""CLI entrypoint - drives core via method registry, mirrors web/feishu.

Startup sequence:
  1. Load .env / config
  2. Build DB engine + sessionmaker (singleton from core/db/session.py)
  3. Seed default user (handle="default")
  4. Get user's "cli-demo" project, create one if absent
  5. Build GoalTutor + configure turn handler (inject runner)
  6. Create a new session under that project (via registry)
  7. REPL: each input -> call_stream("turn.send") -> render

Stage 2: wires GoalTutor as TurnRunner via turn.configure_runner().
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from berry.assistants.learning.tutor import GoalTutor
from berry.channels.cli.approval import CliApprovalChannel
from berry.channels.cli.renderer import render
from berry.config import settings
from berry.core.agent.approval import WhitelistPolicy
from berry.core.agent.events import AgentEvent
from berry.core.agent.runtime import ConversationRuntime
from berry.core.agent.tool_registry import ToolRegistry
from berry.core.db.repos.project_repo import ProjectRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.core.db.session import async_session_factory, engine
from berry.core.llm.adapters.anthropic_messages import AnthropicMessagesAdapter
from berry.core.llm.adapters.base import Adapter
from berry.core.llm.adapters.openai_completions import OpenAICompletionsAdapter
from berry.core.llm.enums import KnownApi
from berry.core.llm.gateway import ModelGateway
from berry.core.llm.registry import ModelRegistry
from berry.core.project.service import ProjectService
from berry.core.tools.files import EditFileTool, ReadFileTool, WriteFileTool
from berry.core.tools.web.fetch import WebFetchTool
from berry.core.tools.web.registry import SearchProviderRegistry
from berry.core.tools.web.search import WebSearchTool
from berry.gateway.methods import register_core
from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.gateway.methods.turn import configure_runner
from berry.protocol.errors import ProtocolError
from berry.protocol.methods_core import SessionMeta

DEFAULT_USER_HANDLE = "default"
DEMO_PROJECT_NAME = "cli-demo"


# ─── Runner construction ────────────────────────────────────


def _build_tutor() -> GoalTutor:
    """Construct GoalTutor + ConversationRuntime from config files."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    models_path = repo_root / "config" / "models.yaml"
    model_registry = ModelRegistry(models_path)
    model_registry.load()
    adapters: dict[str, Adapter] = {
        KnownApi.OPENAI_COMPLETIONS.value: OpenAICompletionsAdapter(),
        KnownApi.ANTHROPIC_MESSAGES.value: AnthropicMessagesAdapter(),
    }
    gateway = ModelGateway(model_registry, adapters)

    search_path = repo_root / "config" / "search.yaml"
    search_registry = SearchProviderRegistry(search_path)
    search_registry.load()

    tool_registry = ToolRegistry(
        [
            WebSearchTool(search_registry),
            WebFetchTool(),
            ReadFileTool(),
            WriteFileTool(),
            EditFileTool(),
        ]
    )
    # write_file / edit_file change persistent state — gate them behind
    # ApprovalChannel (CLI: Y/n prompt). read_file / web_* are auto-allowed.
    policy = WhitelistPolicy({"write_file", "edit_file"})
    approval_channel = CliApprovalChannel()

    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=tool_registry,
        approval_policy=policy,
        approval_channel=approval_channel,
        db_session_factory=async_session_factory,
        model_id="main",
    )
    return GoalTutor.from_settings(
        runtime=runtime,
        settings={
            "language": settings.language,
            "notes_dir": settings.notes_dir,
        },
    )


async def _seed_user() -> UUID:
    async with async_session_factory() as db:
        user = await UserRepo(db).get_or_create_by_handle(
            handle=DEFAULT_USER_HANDLE,
            display_name="Default User",
        )
        return user.id


async def _ensure_demo_project(user_id: UUID) -> UUID:
    """Find or create the cli-demo project."""
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
            title="CLI Demo",
            domain="learning",
            workspace_path=ws_path,
        )
        svc.init_workspace(project)
        return project.id


def _make_ctx(
    *, user_id: UUID, project_id: UUID, db: Any
) -> CallContext:
    return CallContext(
        user_id=user_id,
        request_id=f"cli-{datetime.now().isoformat()}",
        transport="cli",
        db=db,
        project_id=project_id,
    )


async def _create_session(
    registry: MethodRegistry, user_id: UUID, project_id: UUID
) -> str:
    async with async_session_factory() as db:
        ctx = _make_ctx(user_id=user_id, project_id=project_id, db=db)
        result = await registry.call(
            "session.create", {"project_id": str(project_id)}, ctx
        )
    assert isinstance(result, SessionMeta)
    return result.id


async def _run_turn(
    registry: MethodRegistry,
    user_id: UUID,
    project_id: UUID,
    session_id: str,
    text: str,
) -> AsyncIterator[AgentEvent]:
    async with async_session_factory() as db:
        ctx = _make_ctx(user_id=user_id, project_id=project_id, db=db)
        async for ev in registry.call_stream(
            "turn.send",
            {"session_id": session_id, "text": text},
            ctx,
        ):
            yield ev  # type: ignore[misc]


async def _async_main() -> None:
    logging.basicConfig(level=logging.WARNING)
    try:
        await _run()
    finally:
        await engine.dispose()


async def _run() -> None:
    user_id = await _seed_user()
    print(f"[demo] user_id     = {user_id}")

    project_id = await _ensure_demo_project(user_id)
    print(f"[demo] project_id  = {project_id}")

    # Wire GoalTutor into turn handler before starting REPL
    configure_runner(_build_tutor())

    registry = MethodRegistry()
    register_core(registry)

    session_id = await _create_session(registry, user_id, project_id)
    print(f"[demo] session_id  = {session_id}")
    print()
    print("berry CLI - 输入消息后回车发送。/quit 退出。")
    print()

    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return
        if not text:
            continue
        if text in {"/quit", "/q", "/exit"}:
            print("bye")
            return

        try:
            async for ev in _run_turn(
                registry, user_id, project_id, session_id, text
            ):
                render(ev)
        except ProtocolError as exc:
            print(f"\n[error] {exc.code}: {exc.message}\n", flush=True)
        except Exception as exc:
            print(f"\n[runtime error] {type(exc).__name__}: {exc}\n", flush=True)


def main() -> None:
    """sync entry point.

    .env loading is handled at berry.config import time (see berry/config.py),
    so we don't need to call load_dotenv() here.
    """
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
