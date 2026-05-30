"""ConversationRuntime — the business-agnostic turn loop.

One turn is "user input → assistant final reply" with any number of tool
calls in between. The runtime is responsible for:

1. Streaming an LlmRequest through ModelGateway, converting LLM-layer
   StreamEvents into AgentEvents that the channel can render.
2. Reassembling each streamed response into a complete LlmResponse, persisting
   it to llm_call_logs and pushing it onto the AgentSession history.
3. For every tool_use the LLM produced: ask ApprovalPolicy whether approval
   is needed, ask ApprovalChannel if so, dispatch the tool from ToolRegistry,
   wrap the result (success or denial or exception) into a ToolResultBlock
   that goes back into the conversation.
4. Repeat until the LLM stops asking for tools, or hit max_inner_loops.

Following claw-code / openclaw pattern: this is a hand-written while loop, no
graph framework. ~300 lines, single file, every decision visible.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from berry.config import settings
from berry.core.agent import events as agent_events
from berry.core.agent.approval import (
    ApprovalChannel,
    ApprovalDecision,
    ApprovalPolicy,
)
from berry.core.agent.persistence import save_message
from berry.core.agent.session import AgentSession
from berry.core.agent.stream_accumulator import StreamAccumulator
from berry.core.agent.tool_registry import ToolRegistry
from berry.core.db.repos.llm_log_repo import LlmLogRepo
from berry.core.llm.gateway import ModelGateway
from berry.core.llm.types import (
    LlmMessage,
    LlmRequest,
    StreamEvent,
    TextDelta,
    ToolCallStart,
    ToolResultBlock,
    ToolUseBlock,
)
from berry.core.tools.base import ToolContext


class DbSessionFactory(Protocol):
    """A zero-arg callable returning an async context manager that yields an
    AsyncSession. ``async_sessionmaker`` instances satisfy this Protocol.

    The runtime uses a fresh AsyncSession per turn — clear transaction
    boundaries, no leaked state between turns.
    """

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]: ...


class ConversationRuntime:
    """Business-agnostic turn loop. Same instance used by learning / work /
    style assistants — they differ only in system prompt + ToolRegistry contents.
    """

    def __init__(
        self,
        *,
        llm_gateway: ModelGateway,
        tool_registry: ToolRegistry,
        approval_policy: ApprovalPolicy,
        approval_channel: ApprovalChannel,
        db_session_factory: DbSessionFactory,
        model_id: str = "main",
        max_inner_loops: int = 20,
    ) -> None:
        self._gateway = llm_gateway
        self._tools = tool_registry
        self._policy = approval_policy
        self._channel = approval_channel
        self._db_factory = db_session_factory
        self._model_id = model_id
        self._max_inner_loops = max_inner_loops

    async def run_turn(
        self,
        session: AgentSession,
        user_text: str,
        system_prompt: str,
    ) -> AsyncIterator[agent_events.AgentEvent]:
        """Run one full turn. Yields AgentEvents; channels render them."""
        async with self._db_factory() as db:
            async for ev in self._do_turn(session, user_text, system_prompt, db):
                yield ev

    async def _do_turn(
        self,
        session: AgentSession,
        user_text: str,
        system_prompt: str,
        db: AsyncSession,
    ) -> AsyncIterator[agent_events.AgentEvent]:
        # 1. Persist + push user message
        user_msg = session.push_user_text(user_text)
        await save_message(session.id, user_msg, db)

        yield agent_events.TurnStart(session_id=session.id)

        log_repo = LlmLogRepo(db)
        ctx = ToolContext(
            session_id=session.id,
            user_id=session.user_id,
            goal_id=None,  # Round 4: GoalTutor will populate this
            db=db,
            data_root=_data_root_default(),
        )

        for _ in range(self._max_inner_loops):
            # 2. Build request from current message history + tool schemas
            request = LlmRequest(
                model=self._model_id,
                messages=list(session.messages),
                system=system_prompt,
                tools=self._tools.schemas() or None,
                stream=True,
            )

            # 3. Stream the LLM call; emit AgentEvents in lock-step; accumulate
            #    the full response so we can persist it after the stream ends.
            accumulator = StreamAccumulator(model_id=self._model_id)
            async for stream_ev in self._gateway.stream(self._model_id, request):
                accumulator.feed(stream_ev)
                forwarded = _stream_event_to_agent_event(stream_ev)
                if forwarded is not None:
                    yield forwarded

            response = accumulator.build_response()

            # 4. Persist: llm_call_logs + assistant message
            await log_repo.append(session.id, request, response)
            assistant_msg = LlmMessage(role="assistant", content=response.content)
            session.push_message(assistant_msg)
            await save_message(session.id, assistant_msg, db)

            # 5. Did the LLM ask to call tools?
            tool_uses = [
                block
                for block in response.content
                if isinstance(block, ToolUseBlock)
            ]
            if not tool_uses:
                # Plain assistant reply — turn done.
                yield agent_events.TurnEnd(
                    stop_reason=response.stop_reason.value
                    if hasattr(response.stop_reason, "value")
                    else str(response.stop_reason)
                )
                return

            # 6. Execute every tool_use serially; collect ToolResultBlocks.
            tool_results: list[ToolResultBlock] = []
            for tool_use in tool_uses:
                result_block = await self._handle_one_tool_use(tool_use, ctx)
                tool_results.append(result_block)
                yield agent_events.ToolResult(
                    id=tool_use.id,
                    output=result_block.output,
                    is_error=result_block.is_error,
                )

            # 7. Send tool results back as a single user-role message
            #    (Anthropic convention: tool_result blocks live in user role).
            tool_msg = LlmMessage(role="user", content=list(tool_results))
            session.push_message(tool_msg)
            await save_message(session.id, tool_msg, db)

            # Loop: re-call the LLM with the new tool_result context.

        # 8. Hard stop — LLM kept asking for tools forever.
        raise RuntimeError(
            f"ConversationRuntime exceeded max_inner_loops={self._max_inner_loops}; "
            f"the LLM did not finish the turn"
        )

    async def _handle_one_tool_use(
        self,
        tool_use: ToolUseBlock,
        ctx: ToolContext,
    ) -> ToolResultBlock:
        """Run one tool_use through policy + channel + execution; convert any
        outcome (denied / errored / succeeded) into a ToolResultBlock the LLM
        can consume. Never raises.
        """
        decision = self._policy.decide(tool_use.name, tool_use.input, ctx)

        if decision is ApprovalDecision.AUTO_DENY:
            return ToolResultBlock(
                tool_use_id=tool_use.id,
                output="auto-denied by policy",
                is_error=True,
            )

        if decision is ApprovalDecision.REQUIRE_APPROVAL:
            allowed = await self._channel.ask(tool_use.name, tool_use.input, ctx)
            if not allowed:
                return ToolResultBlock(
                    tool_use_id=tool_use.id,
                    output="user denied",
                    is_error=True,
                )

        # Either AUTO_ALLOW or REQUIRE_APPROVAL+approved — execute.
        try:
            tool = self._tools.get(tool_use.name)
        except KeyError:
            return ToolResultBlock(
                tool_use_id=tool_use.id,
                output=f"tool not registered: {tool_use.name}",
                is_error=True,
            )

        try:
            output = await tool.execute(tool_use.input, ctx)
        except Exception as exc:
            return ToolResultBlock(
                tool_use_id=tool_use.id,
                output=f"tool error ({type(exc).__name__}): {exc}",
                is_error=True,
            )

        return ToolResultBlock(
            tool_use_id=tool_use.id,
            output=output,
            is_error=False,
        )


# ─── helpers ────────────────────────────────────────────────────────────


def _stream_event_to_agent_event(
    ev: StreamEvent,
) -> agent_events.AgentEvent | None:
    """Forward a small subset of LLM-layer StreamEvents to channel-facing
    AgentEvents. Internal events (MessageStart, ToolCallDelta, MessageStop,
    UsageEvent, StreamError) are absorbed by StreamAccumulator and not
    surfaced — channels don't need them.
    """
    if isinstance(ev, TextDelta):
        return agent_events.TextDelta(text=ev.text)
    if isinstance(ev, ToolCallStart):
        # Args aren't known yet at start-of-call (they stream in via deltas).
        # Channels that need full args should listen for ToolResult instead.
        return agent_events.ToolCallStart(id=ev.id, name=ev.name, args={})
    return None


def _data_root_default() -> Path:
    """Resolve the data root and ensure it exists.

    Round 2 doesn't have workspace tools yet; ToolContext just needs a
    valid Path. Round 3 (workspace tools) will start writing under this.
    """
    root = settings.data_root
    root.mkdir(parents=True, exist_ok=True)
    return root
