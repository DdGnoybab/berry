"""Repository for the `sessions` table.

A Session is one agent-conversation lifecycle. The ID is also used as the
LangGraph thread_id (see berry-db-schema.md §4.2).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import Session
from berry.domain.enums import Channel, SessionStatus


class SessionRepo:
    """CRUD for sessions, plus a `get_or_create` shortcut for the common
    "find current active session for this user+chat" case.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_or_create(
        self,
        user_id: UUID,
        channel: Channel,
        chat_id: str | None,
    ) -> Session:
        """Reuse an existing active session for (user, channel, chat_id),
        else create a new one.
        """
        stmt = select(Session).where(
            Session.user_id == user_id,
            Session.channel == channel.value,
            Session.channel_chat_id == chat_id,
            Session.status == SessionStatus.ACTIVE.value,
        )
        result = await self._db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

        new = Session(
            user_id=user_id,
            channel=channel.value,
            channel_chat_id=chat_id,
            status=SessionStatus.ACTIVE.value,
        )
        self._db.add(new)
        await self._db.commit()
        await self._db.refresh(new)
        return new

    async def get_by_id(self, session_id: UUID) -> Session | None:
        result = await self._db.execute(select(Session).where(Session.id == session_id))
        return result.scalar_one_or_none()

    async def update_status(
        self,
        session_id: UUID,
        status: SessionStatus,
    ) -> None:
        await self._db.execute(
            update(Session).where(Session.id == session_id).values(status=status.value)
        )
        await self._db.commit()

    async def list_active_by_user(self, user_id: UUID) -> list[Session]:
        result = await self._db.execute(
            select(Session)
            .where(
                Session.user_id == user_id,
                Session.status == SessionStatus.ACTIVE.value,
            )
            .order_by(Session.updated_at.desc())
        )
        return list(result.scalars().all())
