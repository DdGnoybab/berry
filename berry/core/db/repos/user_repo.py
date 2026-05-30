"""Repository for the `users` table.

External-system identity (feishu open_id, cli static id) maps to internal
User rows via (external_source, external_id) UNIQUE constraint.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import User


class UserRepo:
    """Lookup / upsert by (external_source, external_id)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_or_get_by_external(
        self,
        external_source: str,
        external_id: str,
        display_name: str,
    ) -> User:
        """Idempotent upsert by (external_source, external_id).

        On conflict, updates `display_name` so renamed users propagate.
        Returns the freshly read or updated row.
        """
        stmt = (
            pg_insert(User)
            .values(
                external_source=external_source,
                external_id=external_id,
                display_name=display_name,
            )
            .on_conflict_do_update(
                index_elements=["external_source", "external_id"],
                set_={"display_name": display_name},
            )
            .returning(User)
        )
        result = await self._db.execute(stmt)
        row = result.scalar_one()
        await self._db.commit()
        # The session may hold a stale instance from a prior call (same PK).
        # Refresh so callers always see the post-upsert state.
        await self._db.refresh(row)
        return row
