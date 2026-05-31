"""CLI entrypoint — assembles ConversationRuntime + real Round 3 tools + CLI channel.

Run:
    uv run python -m berry.entrypoints.cli

Round 3 wires the real production tool set:
- web_search    (Tavily) — auto-allow
- web_fetch                — auto-allow
- read_md                  — auto-allow
- list_workspace           — auto-allow
- write_md                 — REQUIRES APPROVAL (writes to disk)
- edit_md                  — REQUIRES APPROVAL (modifies existing file)

A fresh "CLI Demo" goal + one default milestone are created on every launch
so the workspace tools have a place to write into. The goal_id / milestone_id
are injected into the system prompt — the LLM passes them as arguments to
write_md / edit_md / list_workspace / read_md.

Round 4 will replace this whole assembly with GoalTutor (real learning
flow). The dummy tools at berry/core/tools/dummy.py stay in the repo for
future ad-hoc debugging but are no longer wired in here.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.workspace.edit_md import EditMdTool
from berry.assistants.learning.tools.workspace.list_workspace import ListWorkspaceTool
from berry.assistants.learning.tools.workspace.read_md import ReadMdTool
from berry.assistants.learning.tools.workspace.write_md import WriteMdTool
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
from berry.core.tools.web.fetch import WebFetchTool
from berry.core.tools.web.registry import SearchProviderRegistry
from berry.core.tools.web.search import WebSearchTool
from berry.domain.enums import Channel

# Repo-root-relative config paths.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MODELS_CONFIG_PATH = _REPO_ROOT / "config" / "models.yaml"
_SEARCH_CONFIG_PATH = _REPO_ROOT / "config" / "search.yaml"


def _system_prompt(goal_id: str, milestone_id: str) -> str:
    """System prompt for the Round 3 CLI demo. The two IDs are baked in so
    workspace tools can be called with the right scope.
    """
    return (
        "You are Berry, a learning assistant prototype.\n"
        "\n"
        "You can call these tools:\n"
        "- web_search(query, n=5)        → list of {title, url, snippet}\n"
        "- web_fetch(url)                → page contents (HTML stripped to text)\n"
        "- write_md(goal_id, milestone_id, filename, content, source_url?, "
        "source_title?, summary?)        → save a new .md file to the workspace\n"
        "- edit_md(material_id, old_string, new_string)       → modify an existing file\n"
        "- read_md(material_id)          → read a saved file's contents\n"
        "- list_workspace(milestone_id)  → list materials saved under a milestone\n"
        "\n"
        "The current workspace is:\n"
        f"  goal_id     = {goal_id}\n"
        f"  milestone_id = {milestone_id}\n"
        "Always pass these exact IDs when calling write_md / list_workspace etc.\n"
        "\n"
        "Default to plain conversation. Use tools only when they materially help "
        "the user — typically: search before answering questions about specific "
        "libraries / docs / current events; fetch when the snippet isn't enough; "
        "save with write_md when the user asks you to record something. "
        "filename must be ASCII letters/digits/underscore/dot/hyphen ending in .md."
    )


def _build_gateway() -> ModelGateway:
    from berry.core.llm.adapters.base import Adapter

    registry = ModelRegistry(_MODELS_CONFIG_PATH)
    registry.load()
    adapters: dict[str, Adapter] = {
        KnownApi.OPENAI_COMPLETIONS.value: OpenAICompletionsAdapter(),
        KnownApi.ANTHROPIC_MESSAGES.value: AnthropicMessagesAdapter(),
    }
    return ModelGateway(registry, adapters)


def _build_search_registry() -> SearchProviderRegistry:
    registry = SearchProviderRegistry(_SEARCH_CONFIG_PATH)
    registry.load()
    return registry


async def _async_main() -> None:
    logging.basicConfig(level=logging.WARNING)

    # ── DB ─────────────────────────────────────────────────
    engine = create_async_engine(settings.database_url_async)
    db_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # ── Seed user, session, demo goal, demo milestone ──────
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
        # Each launch creates a NEW demo goal — keeps every launch's files
        # in their own data/goals/<gid>/... folder so `ls data/goals/`
        # shows a directory per session. Cleanup is left to the user.
        goal = await GoalRepo(setup_db).create(
            user_id=user.id,
            title="CLI Demo",
            workspace_path=f"goals/{user.id}/cli-demo",
            domain="learning",
        )
        milestones = await MilestoneRepo(setup_db).insert_batch(
            goal.id, [("demo milestone", "Round 3 demo workspace")]
        )
        milestone = milestones[0]

    # ── Build registries / runtime ─────────────────────────
    gateway = _build_gateway()
    search_registry = _build_search_registry()

    tools = ToolRegistry(
        [
            WebSearchTool(search_registry),
            WebFetchTool(),
            WriteMdTool(),
            EditMdTool(),
            ReadMdTool(),
            ListWorkspaceTool(),
        ]
    )
    # Only writes / edits need explicit approval; reads / searches auto-allow.
    policy = WhitelistPolicy({"write_md", "edit_md"})
    approval_channel = CliApprovalChannel()

    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=tools,
        approval_policy=policy,
        approval_channel=approval_channel,
        db_session_factory=db_session_factory,
        model_id="main",
    )

    # ── Load AgentSession ──────────────────────────────────
    async with db_session_factory() as load_db:
        agent_session = await load_agent_session(session.id, load_db)
    if agent_session is None:
        raise RuntimeError(f"could not load just-created session {session.id}")

    # ── Print demo header so user sees the IDs at a glance ─
    print(
        f"[demo] goal_id     = {goal.id}\n"
        f"[demo] milestone_id = {milestone.id}\n"
        f"[demo] data_root   = {settings.data_root.resolve()}\n",
        flush=True,
    )

    # ── Run REPL ───────────────────────────────────────────
    # Round 1 of Round 4: run_repl now expects a TurnRunner Protocol
    # (not (runtime, system_prompt)). Wrap the bare ConversationRuntime
    # with a closure that binds the system prompt. Round 4 Step 4 replaces
    # this whole block with GoalTutor (which IS a TurnRunner).
    system_prompt = _system_prompt(str(goal.id), str(milestone.id))

    from collections.abc import AsyncIterator

    from berry.core.agent.events import AgentEvent
    from berry.core.agent.session import AgentSession as AgentSessionType

    class _BoundPromptRunner:
        async def run_turn(
            self,
            agent_session: AgentSessionType,
            user_text: str,
        ) -> AsyncIterator[AgentEvent]:
            async for ev in runtime.run_turn(
                agent_session, user_text, system_prompt=system_prompt
            ):
                yield ev

    try:
        await run_repl(_BoundPromptRunner(), agent_session)
    finally:
        await engine.dispose()


def main() -> None:
    """Sync entry point — what `python -m berry.entrypoints.cli` calls.

    Loads .env so ${DEEPSEEK_KEY}, ${TAVILY_KEY} get picked up by the
    yaml ${VAR} substitution layer.
    """
    from dotenv import load_dotenv

    load_dotenv()
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
