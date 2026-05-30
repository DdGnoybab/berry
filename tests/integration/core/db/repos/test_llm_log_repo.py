"""Integration tests for LlmLogRepo."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import LlmCallLog
from berry.core.db.repos.llm_log_repo import LlmLogRepo
from berry.core.db.repos.session_repo import SessionRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.core.llm.enums import StopReason
from berry.core.llm.types import (
    LlmMessage,
    LlmRequest,
    LlmResponse,
    TextBlock,
    Usage,
)
from berry.domain.enums import Channel


async def _make_session(db_session: AsyncSession, suffix: str):
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="feishu",
        external_id=f"ou_llmlog_{suffix}",
        display_name=f"LlmLog {suffix}",
    )
    return await SessionRepo(db_session).get_or_create(
        user_id=user.id,
        channel=Channel.FEISHU,
        chat_id=f"chat_llmlog_{suffix}",
    )


@pytest.mark.asyncio
async def test_append_persists_request_and_response(
    db_session: AsyncSession,
) -> None:
    session = await _make_session(db_session, "basic")
    repo = LlmLogRepo(db_session)

    request = LlmRequest(
        model="claude-sonnet-4-6",
        messages=[LlmMessage.user("hello")],
        system="You are helpful.",
        max_tokens=1024,
        temperature=0.7,
    )
    response = LlmResponse(
        id="msg_test_001",
        model="claude-sonnet-4-6",
        content=[TextBlock(text="Hi there!")],
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=10, output_tokens=5),
    )

    row = await repo.append(session.id, request, response)
    assert row.id is not None
    assert row.session_id == session.id

    # Round-trip: jsonb columns must rehydrate to original LlmRequest/LlmResponse
    rehydrated_req = LlmRequest.model_validate(row.request)
    rehydrated_resp = LlmResponse.model_validate(row.response)
    assert rehydrated_req.model == "claude-sonnet-4-6"
    assert rehydrated_req.messages[0].content[0].text == "hello"
    assert rehydrated_req.system == "You are helpful."
    assert rehydrated_resp.id == "msg_test_001"
    assert rehydrated_resp.usage.input_tokens == 10
    assert rehydrated_resp.stop_reason == StopReason.END_TURN


@pytest.mark.asyncio
async def test_append_with_optional_fields_omitted(
    db_session: AsyncSession,
) -> None:
    """Request with only required fields should round-trip cleanly."""
    session = await _make_session(db_session, "minimal")
    repo = LlmLogRepo(db_session)
    request = LlmRequest(
        model="claude-sonnet-4-6",
        messages=[LlmMessage.user("ping")],
    )
    response = LlmResponse(
        id="msg_test_002",
        model="claude-sonnet-4-6",
        content=[TextBlock(text="pong")],
        stop_reason=StopReason.END_TURN,
        usage=Usage(),
    )
    row = await repo.append(session.id, request, response)
    assert row.id is not None
    rehydrated_req = LlmRequest.model_validate(row.request)
    assert rehydrated_req.system is None
    assert rehydrated_req.tools is None


@pytest.mark.asyncio
async def test_append_visible_via_select(db_session: AsyncSession) -> None:
    """The committed row is visible to a separate SELECT in the same session."""
    session = await _make_session(db_session, "select")
    repo = LlmLogRepo(db_session)
    await repo.append(
        session.id,
        LlmRequest(model="claude-sonnet-4-6", messages=[LlmMessage.user("x")]),
        LlmResponse(
            id="msg_select",
            model="claude-sonnet-4-6",
            content=[TextBlock(text="y")],
            stop_reason=StopReason.END_TURN,
            usage=Usage(),
        ),
    )
    result = await db_session.execute(select(LlmCallLog).where(LlmCallLog.session_id == session.id))
    rows = list(result.scalars().all())
    assert len(rows) == 1
