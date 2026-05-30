"""Repository for the `messages` table.

Each row = one LlmMessage. Multi-block messages (assistant with thinking
+ text + tool_use, user with tool_result) are stored as a JSONB list in
`content`.

Note: messages.content holds list[ContentBlock] directly, not the
simple {"text": "..."} shape originally sketched in berry-db-schema.md
§4.3 — see Round 1 spec for rationale.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import Message
from berry.core.llm.types import LlmMessage


class MessageRepo:
    """Append-only writes; ordered reads by created_at."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def append(self, session_id: UUID, msg: LlmMessage) -> Message:
        """Insert one LlmMessage as a row. Returns the persisted row."""
        # model_dump(mode="json") yields jsonb-friendly primitives
        # (enums → strings, UUID → strings, datetime → ISO strings).
        content_jsonb = msg.model_dump(mode="json")["content"]
        row = Message(
            session_id=session_id,
            role=msg.role,
            content=content_jsonb,
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def list_by_session(self, session_id: UUID) -> list[Message]:
        """All messages for the session, oldest first."""
        result = await self._db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list(result.scalars().all())
