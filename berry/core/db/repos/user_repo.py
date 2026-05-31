"""Repository for the `users` table.

handle 替代之前的 (external_source, external_id) 联合键。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import User


class UserRepo:
    """Lookup / upsert by handle."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_or_create_by_handle(
        self,
        handle: str,
        display_name: str,
    ) -> User:
        """Idempotent upsert by handle.

        On conflict, updates display_name so renamed users propagate.
        """
        stmt = (
            pg_insert(User)
            .values(handle=handle, display_name=display_name)
            .on_conflict_do_update(
                index_elements=["handle"],
                set_={"display_name": display_name},
            )
            .returning(User)
        )
        result = await self._db.execute(stmt)
        row = result.scalar_one()
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def get_by_handle(self, handle: str) -> User | None:
        result = await self._db.execute(
            select(User).where(User.handle == handle)  # type: ignore[arg-type]
        )
        return result.scalar_one_or_none()
