"""CLI entrypoint — assembles ConversationRuntime + dummy tools + CLI channel.

Run:
    uv run python -m berry.entrypoints.cli

Round 2 wires up the bare minimum that proves the turn loop works against
real DeepSeek:
- ModelGateway with both adapters loaded (we use the ``main`` alias →
  ``deepseek-anthropic``)
- ToolRegistry containing only dummy ``echo_tool`` + ``fail_tool``
- WhitelistPolicy({"echo_tool"}) — echo needs approval, fail does not
  (so we exercise both approval-required and auto-allow paths in one demo)
- CliApprovalChannel — stdin Y/n
- A fresh user/session per CLI launch (SessionRepo.create_new closes any
  prior active CLI session for this user)

Round 4 will replace the ToolRegistry contents and the system prompt with
GoalTutor's set, leaving everything else here untouched.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from berry.channels.cli.approval import CliApprovalChannel
from berry.channels.cli.client import run_repl
from berry.config import settings
from berry.core.agent.approval import WhitelistPolicy
from berry.core.agent.persistence import load_agent_session
from berry.core.agent.runtime import ConversationRuntime
from berry.core.agent.tool_registry import ToolRegistry
from berry.core.db.repos.session_repo import SessionRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.core.llm.adapters.anthropic_messages import AnthropicMessagesAdapter
from berry.core.llm.adapters.openai_completions import OpenAICompletionsAdapter
from berry.core.llm.enums import KnownApi
from berry.core.llm.gateway import ModelGateway
from berry.core.llm.registry import ModelRegistry
from berry.core.tools.dummy import EchoTool, FailTool
from berry.domain.enums import Channel

# Round 2 system prompt — minimal, just gives the LLM enough context to know
# it can call echo_tool / fail_tool. Round 4 overrides this with the
# learning-domain prompt.
SYSTEM_PROMPT = (
    "You are Berry, a helpful assistant under development. "
    "Two test tools are available: `echo_tool` (echoes back text) and "
    "`fail_tool` (intentionally fails — only use when explicitly asked to "
    "test error handling). Default to plain conversation; only call a tool "
    "when the user clearly asks you to."
)

# Models config lives in repo root.
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "models.yaml"


def _build_gateway() -> ModelGateway:
    from berry.core.llm.adapters.base import Adapter

    registry = ModelRegistry(_CONFIG_PATH)
    registry.load()
    adapters: dict[str, Adapter] = {
        KnownApi.OPENAI_COMPLETIONS.value: OpenAICompletionsAdapter(),
        KnownApi.ANTHROPIC_MESSAGES.value: AnthropicMessagesAdapter(),
    }
    return ModelGateway(registry, adapters)


async def _async_main() -> None:
    # Quiet down sqlalchemy / httpx info logs that pollute the REPL.
    logging.basicConfig(level=logging.WARNING)

    # ── Build engine + session factory ─────────────────────
    engine = create_async_engine(settings.database_url_async)
    db_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # ── Seed a fresh user + session for this CLI launch ────
    async with db_session_factory() as setup_db:
        user = await UserRepo(setup_db).create_or_get_by_external(
            external_source="cli",
            external_id="cli_local",
            display_name="CLI Local",
        )
        session = await SessionRepo(setup_db).create_new(
            user_id=user.id,
            channel=Channel.CLI,
        )

    # ── Build the runtime ──────────────────────────────────
    gateway = _build_gateway()
    tools = ToolRegistry([EchoTool(), FailTool()])
    policy = WhitelistPolicy({"echo_tool"})
    approval_channel = CliApprovalChannel()

    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=tools,
        approval_policy=policy,
        approval_channel=approval_channel,
        db_session_factory=db_session_factory,
        model_id="main",
    )

    # ── Load AgentSession (empty messages list since we just created it) ──
    async with db_session_factory() as load_db:
        agent_session = await load_agent_session(session.id, load_db)
    if agent_session is None:
        raise RuntimeError(f"could not load just-created session {session.id}")

    # ── Run REPL ───────────────────────────────────────────
    try:
        await run_repl(runtime, agent_session, system_prompt=SYSTEM_PROMPT)
    finally:
        await engine.dispose()


def main() -> None:
    """Sync entry point — what `python -m berry.entrypoints.cli` calls.

    Note: pydantic-settings already loads ``.env`` when ``Settings`` is
    instantiated (see ``berry.config``). We additionally need ``DEEPSEEK_KEY``
    in ``os.environ`` for ``models.yaml``'s ``${VAR}`` substitution — load
    .env explicitly here to cover that case.
    """
    from dotenv import load_dotenv

    load_dotenv()
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
