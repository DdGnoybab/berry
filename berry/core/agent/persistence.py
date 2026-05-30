"""AgentSession <-> DB conversion.

Design:
- Incremental persistence: each push_message → one INSERT
- Read-only `load`: never mutates the DB
- Caller-explicit save: no dirty tracking, no implicit flush

Round 1 only exposes the bare minimum used by Round 3 and beyond.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession as DbSession

from berry.core.agent.session import AgentSession
from berry.core.db.models import Message
from berry.core.db.repos.message_repo import MessageRepo
from berry.core.db.repos.session_repo import SessionRepo
from berry.core.llm.types import LlmMessage
from berry.domain.enums import Channel, SessionStatus


async def load_agent_session(
    session_id: UUID, db: DbSession,
) -> AgentSession | None:
    """Fetch sessions row + all messages rows; reassemble AgentSession.

    Returns None if the session does not exist.
    """
    session_row = await SessionRepo(db).get_by_id(session_id)
    if session_row is None:
        return None

    message_rows = await MessageRepo(db).list_by_session(session_id)
    messages = [_message_row_to_llm(row) for row in message_rows]

    return AgentSession(
        id=session_row.id,
        user_id=session_row.user_id,
        channel=Channel(session_row.channel),
        chat_id=session_row.channel_chat_id,
        status=SessionStatus(session_row.status),
        title=session_row.title,
        messages=messages,
        created_at=session_row.created_at,
        updated_at=session_row.updated_at,
    )


async def save_message(
    session_id: UUID, message: LlmMessage, db: DbSession,
) -> UUID:
    """Persist one LlmMessage as a row in `messages`. Returns the new row id."""
    row = await MessageRepo(db).append(session_id, message)
    return row.id


def _message_row_to_llm(row: Message) -> LlmMessage:
    """DB row → LlmMessage. content jsonb is validated against the discriminated
    union, so unknown block types raise immediately rather than silently passing."""
    return LlmMessage.model_validate(
        {"role": row.role, "content": row.content}
    )
