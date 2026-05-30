"""End-to-end tests for ConversationRuntime against real Postgres + a fake LLM.

These tests exercise the full turn loop without spending tokens or depending
on a live model. The fake gateway replays a scripted sequence of stream
events, so we control exactly what "LLM" output looks like for each test.

What's covered:
- happy path: LLM tool_use -> approved -> tool runs -> result -> final reply
- denial path: LLM tool_use -> ApprovalChannel returns False -> "user denied" surfaced to LLM
- error path: LLM tool_use -> tool raises -> error string surfaced to LLM
- runaway path: LLM keeps requesting tools -> max_inner_loops raises RuntimeError

What's NOT covered here:
- Real network calls to DeepSeek (those are in scripts/llm_smoke.py and the
  manual REPL session)
- StreamAccumulator internals (covered in tests/unit/core/agent/test_stream_accumulator.py)
- ApprovalPolicy internals (covered in tests/unit/core/agent/test_approval.py)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.agent import events as agent_events
from berry.core.agent.approval import WhitelistPolicy
from berry.core.agent.persistence import load_agent_session
from berry.core.agent.runtime import ConversationRuntime
from berry.core.agent.tool_registry import ToolRegistry
from berry.core.db.models import LlmCallLog
from berry.core.db.repos.message_repo import MessageRepo
from berry.core.db.repos.session_repo import SessionRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.core.llm.enums import StopReason
from berry.core.llm.types import (
    LlmRequest,
    LlmResponse,
    MessageStart,
    MessageStop,
    StreamEvent,
    TextDelta,
    ToolCallDelta,
    ToolCallStart,
    Usage,
    UsageEvent,
)
from berry.core.tools.dummy import EchoTool, FailTool
from berry.domain.enums import Channel
from tests._fakes.auto_approve import AutoApproveChannel, AutoDenyChannel

# ─── Fake LLM gateway ───────────────────────────────────────────────────


class FakeLlmGateway:
    """Replays a list of pre-scripted stream-event lists. Each call to
    ``stream`` consumes one entry. Mirrors ModelGateway's signature enough
    for ConversationRuntime to use it.
    """

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self._scripts = list(scripts)
        self._call_count = 0
        self.received_requests: list[LlmRequest] = []

    async def stream(
        self, model_id: str, request: LlmRequest
    ) -> AsyncIterator[StreamEvent]:
        self.received_requests.append(request)
        if self._call_count >= len(self._scripts):
            raise AssertionError(
                f"FakeLlmGateway ran out of scripts at call {self._call_count + 1}"
            )
        script = self._scripts[self._call_count]
        self._call_count += 1
        for event in script:
            yield event

    async def invoke(self, model_id: str, request: LlmRequest) -> LlmResponse:
        # Not exercised by ConversationRuntime (always streams) but keep the
        # method present so duck typing holds.
        raise NotImplementedError


# ─── Test scaffolding ───────────────────────────────────────────────────


def _factory_from_session(db_session: AsyncSession):
    """Wrap a single AsyncSession (from the conftest fixture) as a
    ``DbSessionFactory`` that the runtime can call once per turn.
    The yielded session is the very same fixture object so test assertions
    (``await db_session.execute(...)``) see what the runtime wrote.
    """

    @asynccontextmanager
    async def factory():
        yield db_session

    return factory


async def _seed_user_and_session(db_session: AsyncSession, suffix: str):
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"runtime_e2e_{suffix}",
        display_name=f"Runtime E2E {suffix}",
    )
    session = await SessionRepo(db_session).create_new(
        user_id=user.id,
        channel=Channel.CLI,
    )
    return user, session


def _tool_use_script(tool_id: str, tool_name: str, args_json: str) -> list[StreamEvent]:
    """Helper: build the stream events for a single LLM 'I want to call this tool' message."""
    return [
        MessageStart(id=f"msg_{tool_id}", model="main"),
        ToolCallStart(id=tool_id, name=tool_name),
        ToolCallDelta(id=tool_id, input_json_delta=args_json),
        MessageStop(stop_reason=StopReason.TOOL_USE),
        UsageEvent(usage=Usage(input_tokens=10, output_tokens=5)),
    ]


def _final_reply_script(text: str) -> list[StreamEvent]:
    """Helper: stream events for a plain text final reply."""
    return [
        MessageStart(id=f"msg_final_{hash(text) & 0xFFFF}", model="main"),
        TextDelta(text=text),
        MessageStop(stop_reason=StopReason.END_TURN),
        UsageEvent(usage=Usage(input_tokens=20, output_tokens=8)),
    ]


# ─── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_happy_path_with_approved_tool(
    db_session: AsyncSession,
) -> None:
    """LLM asks to call echo_tool → AutoApprove approves → tool succeeds →
    LLM gets the result and emits a final reply. Persistence: 4 messages,
    2 llm_call_logs.
    """
    _, session = await _seed_user_and_session(db_session, "happy")
    agent_session = await load_agent_session(session.id, db_session)
    assert agent_session is not None

    gateway = FakeLlmGateway([
        _tool_use_script("t1", "echo_tool", '{"text": "hello"}'),
        _final_reply_script("Echoed: hello"),
    ])
    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=ToolRegistry([EchoTool()]),
        approval_policy=WhitelistPolicy({"echo_tool"}),
        approval_channel=AutoApproveChannel(),
        db_session_factory=_factory_from_session(db_session),
    )

    events = [
        ev
        async for ev in runtime.run_turn(
            agent_session, "say hello via echo_tool", system_prompt="be helpful"
        )
    ]

    # First event must be TurnStart, last must be TurnEnd.
    assert isinstance(events[0], agent_events.TurnStart)
    assert isinstance(events[-1], agent_events.TurnEnd)

    # Tool call surfaced to channel + tool result surfaced to channel.
    tool_calls = [ev for ev in events if isinstance(ev, agent_events.ToolCallStart)]
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "echo_tool"

    tool_results = [ev for ev in events if isinstance(ev, agent_events.ToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].is_error is False
    assert tool_results[0].output == "hello"

    # Final TextDelta carries the assistant reply.
    text_deltas = [ev for ev in events if isinstance(ev, agent_events.TextDelta)]
    assert any("Echoed: hello" in ev.text for ev in text_deltas)

    # Persistence: 4 messages (user, assistant_tool_use, user_tool_result, assistant_final).
    messages = await MessageRepo(db_session).list_by_session(session.id)
    assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]

    # Persistence: 2 LLM call logs.
    log_count = await db_session.execute(
        select(LlmCallLog).where(LlmCallLog.session_id == session.id)
    )
    assert len(list(log_count.scalars().all())) == 2


@pytest.mark.asyncio
async def test_runtime_denial_path_surfaces_user_denied(
    db_session: AsyncSession,
) -> None:
    """LLM asks to call echo_tool → AutoDeny rejects → ToolResultBlock with
    output='user denied', is_error=True flows back to LLM → LLM apologizes.
    """
    _, session = await _seed_user_and_session(db_session, "deny")
    agent_session = await load_agent_session(session.id, db_session)
    assert agent_session is not None

    gateway = FakeLlmGateway([
        _tool_use_script("t1", "echo_tool", '{"text": "blocked"}'),
        _final_reply_script("Sorry, can't do that."),
    ])
    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=ToolRegistry([EchoTool()]),
        approval_policy=WhitelistPolicy({"echo_tool"}),
        approval_channel=AutoDenyChannel(),
        db_session_factory=_factory_from_session(db_session),
    )

    events = [
        ev
        async for ev in runtime.run_turn(
            agent_session, "echo something", system_prompt="be helpful"
        )
    ]

    tool_results = [ev for ev in events if isinstance(ev, agent_events.ToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].is_error is True
    assert tool_results[0].output == "user denied"

    # Persistence: same 4 messages — denial is rendered as a tool_result, not a special path.
    messages = await MessageRepo(db_session).list_by_session(session.id)
    assert len(messages) == 4
    # The third message (user role with tool_result block) carries the denial.
    third = messages[2]
    assert third.role == "user"
    # content is a JSONB list; the tool_result block should have is_error=True
    blocks = third.content
    assert any(
        block.get("type") == "tool_result" and block.get("is_error") is True
        for block in blocks
    )


@pytest.mark.asyncio
async def test_runtime_error_path_wraps_tool_exception(
    db_session: AsyncSession,
) -> None:
    """LLM asks to call fail_tool (auto-allow per policy) → tool raises →
    runtime catches it → ToolResultBlock(is_error=True, output='tool error...')
    → LLM gets that and emits a final reply.
    """
    _, session = await _seed_user_and_session(db_session, "error")
    agent_session = await load_agent_session(session.id, db_session)
    assert agent_session is not None

    gateway = FakeLlmGateway([
        _tool_use_script("t1", "fail_tool", "{}"),
        _final_reply_script("The tool failed as expected."),
    ])
    # fail_tool not in whitelist → auto-allow, no approval prompt.
    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=ToolRegistry([FailTool()]),
        approval_policy=WhitelistPolicy({"echo_tool"}),
        approval_channel=AutoApproveChannel(),
        db_session_factory=_factory_from_session(db_session),
    )

    events = [
        ev
        async for ev in runtime.run_turn(
            agent_session, "test the failure path", system_prompt="be helpful"
        )
    ]

    tool_results = [ev for ev in events if isinstance(ev, agent_events.ToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].is_error is True
    assert "RuntimeError" in tool_results[0].output
    assert "intentionally failed" in tool_results[0].output


@pytest.mark.asyncio
async def test_runtime_aborts_on_max_inner_loops(
    db_session: AsyncSession,
) -> None:
    """If the LLM keeps requesting tools forever, runtime should bail with
    RuntimeError after max_inner_loops. We script 5 tool_use rounds and
    cap the runtime at 3.
    """
    _, session = await _seed_user_and_session(db_session, "loop")
    agent_session = await load_agent_session(session.id, db_session)
    assert agent_session is not None

    gateway = FakeLlmGateway([
        _tool_use_script(f"t{i}", "echo_tool", '{"text": "loop"}') for i in range(5)
    ])
    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=ToolRegistry([EchoTool()]),
        approval_policy=WhitelistPolicy(set()),  # auto-allow everything
        approval_channel=AutoApproveChannel(),
        db_session_factory=_factory_from_session(db_session),
        max_inner_loops=3,
    )

    with pytest.raises(RuntimeError, match="max_inner_loops"):
        # Drain the async generator; the error fires inside it.
        async for _ev in runtime.run_turn(
            agent_session, "loop forever", system_prompt="be helpful"
        ):
            pass


@pytest.mark.asyncio
async def test_runtime_no_tool_calls_finishes_in_one_round(
    db_session: AsyncSession,
) -> None:
    """When the LLM replies with just text (no tool_use), the runtime must
    finish after a single LLM call — 2 messages persisted, 1 llm_call_log.
    """
    _, session = await _seed_user_and_session(db_session, "plain")
    agent_session = await load_agent_session(session.id, db_session)
    assert agent_session is not None

    gateway = FakeLlmGateway([_final_reply_script("Hi there!")])
    runtime = ConversationRuntime(
        llm_gateway=gateway,
        tool_registry=ToolRegistry([]),
        approval_policy=WhitelistPolicy(set()),
        approval_channel=AutoApproveChannel(),
        db_session_factory=_factory_from_session(db_session),
    )

    events = [
        ev async for ev in runtime.run_turn(agent_session, "hi", system_prompt="hi")
    ]
    text = "".join(
        ev.text for ev in events if isinstance(ev, agent_events.TextDelta)
    )
    assert text == "Hi there!"

    messages = await MessageRepo(db_session).list_by_session(session.id)
    assert [m.role for m in messages] == ["user", "assistant"]

    log_rows = await db_session.execute(
        select(LlmCallLog).where(LlmCallLog.session_id == session.id)
    )
    assert len(list(log_rows.scalars().all())) == 1
