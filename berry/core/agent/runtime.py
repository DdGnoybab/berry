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

import os
from collections.abc import AsyncIterator, Callable
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
from berry.core.agent.compaction import (
    CompactionConfig,
    apply_compaction_pipeline,
    estimate_tokens,
    reactive_compact,
)
from berry.core.agent.hook import (
    HookRunner,
    HookVerdictAction,
)
from berry.core.agent.session import AgentSession
from berry.core.agent.stream_accumulator import StreamAccumulator
from berry.core.agent.tool_registry import ToolRegistry
from berry.core.db.repos.llm_log_repo import LlmLogRepo
from berry.core.llm.gateway import ModelGateway
from berry.core.llm.types import (
    LlmMessage,
    LlmRequest,
    StreamEvent,
    TextBlock,
    TextDelta,
    ToolCallStart,
    ToolResultBlock,
    ToolUseBlock,
)
from berry.core.tools.base import ToolContext
from berry.utils.unicode import strip_surrogates


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
        hook_runner: HookRunner | None = None,
        model_id: str = "main",
        max_inner_loops: int = 20,
        auto_compact_threshold: int = 100_000,
        todo_nag_rounds: int = 3,
        cwd_resolver: Callable[[str], Path] | None = None,
    ) -> None:
        self._gateway = llm_gateway
        self._tools = tool_registry
        self._policy = approval_policy
        self._channel = approval_channel
        self._hook_runner = hook_runner
        self._db_factory = db_session_factory
        self._model_id = model_id
        self._max_inner_loops = max_inner_loops
        self._auto_compact_threshold = auto_compact_threshold
        self._todo_nag_rounds = todo_nag_rounds
        self._cwd_resolver = cwd_resolver

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
        # 1. Push user message (file persistence is owned by the caller via SessionStore)
        session.push_user_text(user_text)

        yield agent_events.TurnStart(session_id=session.id)

        log_repo = LlmLogRepo(db)
        cwd = self._cwd_resolver(session.id) if self._cwd_resolver else _cwd_default()
        ctx = ToolContext(
            session_id=session.id,
            user_id=session.user_id,
            goal_id=None,
            db=db,
            data_root=_data_root_default(),
            cwd=cwd,
        )

        rounds_since_todo = 0
        reactive_retries = 0

        # ─── Memory: load relevant memories into context ───
        await self._load_relevant_memories(session, ctx)

        for _ in range(self._max_inner_loops):
            # ─── 四层压缩管线（每轮 LLM 调用前） ───
            session.messages = list(apply_compaction_pipeline(
                list(session.messages),
                CompactionConfig(
                    auto_compact_threshold=self._auto_compact_threshold,
                    persist_dir=cwd / ".berry",
                ),
            )[0])

            # Nag reminder: inject if todo_write hasn't been called for a while.
            if self._todo_nag_rounds > 0 and rounds_since_todo >= self._todo_nag_rounds:
                if _has_pending_todos(ctx.cwd):
                    session.push_message(LlmMessage(
                        role="user",
                        content=[TextBlock(
                            text="<reminder>You have pending todos. "
                            "Update your task list to track progress.</reminder>"
                        )],
                    ))
                rounds_since_todo = 0

            # Last-chance tool-pairing sanitize before the API call. Compaction
            # passes (snip / micro / auto) can cut a tool_use → tool_result
            # pair across their kept-window boundary, leaving a tool_result
            # whose tool_use isn't in the request anymore (or vice versa).
            # Anthropic 400s on this. Strip the orphans here so the wire
            # request is always self-consistent.
            request_messages = _strip_unpaired_tool_blocks(list(session.messages))

            request = LlmRequest(
                model=self._model_id,
                messages=request_messages,
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

            # 4. Persist: llm_call_logs + push assistant message
            await log_repo.append(
                user_id=session.user_id,
                project_id=None,
                session_id=session.id,  # already a string
                model=self._model_id,
                request=request.model_dump(),
                response=response.model_dump(),
            )
            assistant_msg = LlmMessage(role="assistant", content=response.content)
            session.push_message(assistant_msg)

            # 5. Did the LLM ask to call tools?
            tool_uses = [
                block
                for block in response.content
                if isinstance(block, ToolUseBlock)
            ]
            if not tool_uses:
                # Plain assistant reply — turn done.
                # ─── Memory: extract + consolidate (fire-and-forget) ───
                await self._extract_and_consolidate(session, ctx)

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

            # Track todo_write calls for nag reminder
            if any(tu.name == "todo_write" for tu in tool_uses):
                rounds_since_todo = 0
            else:
                rounds_since_todo += 1

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
        """Run one tool_use through hook → policy → channel → execution; convert
        any outcome into a ToolResultBlock the LLM can consume.  Never raises.
        """
        # 1. PreToolUse hooks (run before policy; first non-DEFER wins)
        if self._hook_runner is not None:
            hook_v = await self._hook_runner.run(
                tool_use.name, tool_use.input, ctx
            )
            if hook_v.action is HookVerdictAction.DENY:
                return ToolResultBlock(
                    tool_use_id=tool_use.id,
                    output=f"denied by hook: {hook_v.reason or 'no reason given'}",
                    is_error=True,
                )
            if hook_v.action is HookVerdictAction.ALLOW:
                return await self._execute_tool(tool_use, ctx)

        # 2. Policy decision
        verdict = self._policy.decide(tool_use.name, tool_use.input, ctx)

        if verdict.decision is ApprovalDecision.AUTO_DENY:
            return ToolResultBlock(
                tool_use_id=tool_use.id,
                output=f"auto-denied by policy: {verdict.reason or 'no reason given'}",
                is_error=True,
            )

        if verdict.decision is ApprovalDecision.REQUIRE_APPROVAL:
            allowed = await self._channel.ask(
                tool_use.name, tool_use.input, ctx, reason=verdict.reason
            )
            if not allowed:
                return ToolResultBlock(
                    tool_use_id=tool_use.id,
                    output=f"user denied (reason: {verdict.reason or 'unspecified'})",
                    is_error=True,
                )

        # Either AUTO_ALLOW or REQUIRE_APPROVAL+approved — execute.
        return await self._execute_tool(tool_use, ctx)

    async def _execute_tool(
        self,
        tool_use: ToolUseBlock,
        ctx: ToolContext,
    ) -> ToolResultBlock:
        """Lookup and execute a tool; wrap result or error into a ToolResultBlock."""
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
                output=strip_surrogates(f"tool error ({type(exc).__name__}): {exc}"),
                is_error=True,
            )

        # Tool outputs become ToolResultBlocks that are pushed back into
        # session.messages for the next LLM turn. Strip lone surrogates here
        # (they can leak in via web_fetch on UTF-8-broken pages) so the next
        # request-body encoding doesn't crash with surrogates_not_allowed.
        return ToolResultBlock(
            tool_use_id=tool_use.id,
            output=strip_surrogates(output),
            is_error=False,
        )

    # ─── Memory integration ───────────────────────────────────────────

    async def _load_relevant_memories(
        self,
        session: AgentSession,
        ctx: ToolContext,
    ) -> None:
        """Select and inject relevant memories into the current turn."""
        try:
            from berry.core.tools.memory.loader import (
                build_memory_injection,
                load_relevant_memories,
                select_relevant_memories,
            )
            from berry.core.tools.memory.store import MemoryStore

            memory_dir = ctx.data_root / "memory"
            store = MemoryStore(memory_dir)
            catalog = store.list_all()
            if not catalog:
                return

            # Get recent user text for matching
            recent_text = _last_user_text(session)
            if not recent_text:
                return

            # Build a lightweight LLM invoker
            async def invoke_llm(prompt: str) -> str:
                from berry.core.llm.types import LlmMessage, TextBlock

                req = LlmRequest(
                    model="classify",
                    messages=[LlmMessage(role="user", content=[TextBlock(text=prompt)])],
                    stream=False,
                )
                resp = await self._gateway.invoke("classify", req)
                for block in resp.content:
                    if hasattr(block, "text"):
                        return block.text
                return ""

            filenames = await select_relevant_memories(
                recent_text, catalog, invoke_llm=invoke_llm
            )
            if not filenames:
                return

            entries = load_relevant_memories(memory_dir, filenames)
            if not entries:
                return

            injection = build_memory_injection(entries)
            if injection:
                from berry.core.llm.types import TextBlock

                session.push_message(LlmMessage(
                    role="user",
                    content=[TextBlock(text=injection)],
                ))
        except Exception:
            logger.warning("memory_load_failed", exc_info=True)

    async def _extract_and_consolidate(
        self,
        session: AgentSession,
        ctx: ToolContext,
    ) -> None:
        """Extract new memories and consolidate if needed. Fire-and-forget."""
        try:
            from berry.core.tools.memory.consolidator import consolidate_memories
            from berry.core.tools.memory.extractor import extract_memories
            from berry.core.tools.memory.store import MemoryStore

            memory_dir = ctx.data_root / "memory"
            store = MemoryStore(memory_dir)

            # Build LLM invoker
            async def invoke_llm(prompt: str) -> str:
                from berry.core.llm.types import LlmMessage, TextBlock

                req = LlmRequest(
                    model="classify",
                    messages=[LlmMessage(role="user", content=[TextBlock(text=prompt)])],
                    stream=False,
                )
                resp = await self._gateway.invoke("classify", req)
                for block in resp.content:
                    if hasattr(block, "text"):
                        return block.text
                return ""

            await extract_memories(session.messages, store, invoke_llm=invoke_llm)
            await consolidate_memories(store, invoke_llm=invoke_llm)
        except Exception:
            logger.warning("memory_extract_consolidate_failed", exc_info=True)


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


def _strip_unpaired_tool_blocks(messages: list[LlmMessage]) -> list[LlmMessage]:
    """Strip orphan tool_use / tool_result blocks from a message list.

    Used as a last-chance sanitize right before sending to the LLM provider.
    Anthropic rejects requests where a ``tool_result`` has no matching
    ``tool_use`` earlier in messages (and vice versa), and any number of
    code paths can produce that state — interrupted streams, compaction
    boundaries cutting through pairs, manually-edited session files, etc.

    Algorithm:
      1. Forward pass: collect tool_use ids and tool_result ids.
      2. Drop tool_result blocks whose tool_use_id wasn't seen.
      3. Drop tool_use blocks with no later tool_result.
      4. If a message becomes empty, drop the message.
    """
    use_ids: set[str] = set()
    result_ids: set[str] = set()
    for msg in messages:
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                use_ids.add(block.id)
            elif isinstance(block, ToolResultBlock):
                result_ids.add(block.tool_use_id)

    orphan_results = result_ids - use_ids
    dangling_uses = use_ids - result_ids
    if not orphan_results and not dangling_uses:
        return messages

    out: list[LlmMessage] = []
    for msg in messages:
        new_blocks = [
            b
            for b in msg.content
            if not (isinstance(b, ToolUseBlock) and b.id in dangling_uses)
            and not (
                isinstance(b, ToolResultBlock)
                and b.tool_use_id in orphan_results
            )
        ]
        if new_blocks:
            out.append(LlmMessage(role=msg.role, content=new_blocks))
    return out


def _cwd_default() -> Path:
    """LLM workspace root for file tools.

    Defaults to the process's current working directory (i.e. wherever the
    user started ``uv run python -m berry.entrypoints.cli``). Override with
    ``BERRY_CWD`` env var — useful for tests and for running berry from one
    directory while pointing the LLM at another.
    """
    override = os.environ.get("BERRY_CWD")
    if override:
        return Path(override).resolve()
    return Path.cwd().resolve()


def _data_root_default() -> Path:
    """Resolve the data root and ensure it exists.

    Round 2 doesn't have workspace tools yet; ToolContext just needs a
    valid Path. Round 3 (workspace tools) will start writing under this.
    """
    root = settings.data_root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _has_pending_todos(cwd: Path) -> bool:
    """Check if there are pending/in_progress todos in the workspace."""
    import json as _json

    todo_path = cwd / ".berry" / "todos.json"
    if not todo_path.is_file():
        return False
    try:
        todos = _json.loads(todo_path.read_text(encoding="utf-8"))
        return any(t.get("status") != "completed" for t in todos)
    except (OSError, _json.JSONDecodeError):
        return False


def _last_user_text(session: AgentSession) -> str:
    """Extract plain text from the last user message."""
    for msg in reversed(session.messages):
        if msg.role != "user":
            continue
        if isinstance(msg.content, str):
            return msg.content
        if isinstance(msg.content, list):
            parts: list[str] = []
            for block in msg.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return " ".join(parts)
    return ""
