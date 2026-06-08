"""Repository for `auth_sessions`."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import AuthSession


class AuthSessionRepo:
    """CRUD for the auth_sessions table."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> AuthSession:
        row = AuthSession(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def get_active(self, token_hash: str) -> AuthSession | None:
        """Return the row only if it exists and not expired."""
        result = await self._db.execute(
            select(AuthSession).where(
                AuthSession.token_hash == token_hash,  # type: ignore[arg-type]
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if row.expires_at <= datetime.now(UTC):
            return None
        return row

    async def delete_by_token_hash(self, token_hash: str) -> None:
        await self._db.execute(
            delete(AuthSession).where(
                AuthSession.token_hash == token_hash,  # type: ignore[arg-type]
            )
        )
        await self._db.commit()

    async def delete_all_for_user(self, user_id: UUID) -> None:
        """强制下线该用户所有设备(改密码 / 删账号时调用)。"""
        await self._db.execute(
            delete(AuthSession).where(
                AuthSession.user_id == user_id,  # type: ignore[arg-type]
            )
        )
        await self._db.commit()
