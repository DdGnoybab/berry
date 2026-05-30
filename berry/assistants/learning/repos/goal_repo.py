"""Repository for the `goals` table.

Lives under assistants/learning/ per ADR-0003: business-specific repos
travel with their assistant. The SQLModel itself is in core/db/models.py
(centralized for alembic autogenerate).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import Goal


class GoalRepo:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: UUID,
        title: str,
        workspace_path: str,
        domain: str = "learning",
    ) -> Goal:
        row = Goal(
            user_id=user_id,
            domain=domain,
            title=title,
            workspace_path=workspace_path,
            status="drafting",
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def get_by_id(self, goal_id: UUID) -> Goal | None:
        result = await self._db.execute(select(Goal).where(Goal.id == goal_id))
        return result.scalar_one_or_none()

    async def get_active_for_user(self, user_id: UUID) -> Goal | None:
        """Return the user's currently active goal, if any.

        Day-1: enforce single active goal at the repo layer (caller's job to
        avoid creating concurrent active goals — see spec §二 "单 goal").
        """
        result = await self._db.execute(
            select(Goal).where(
                Goal.user_id == user_id,
                Goal.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def set_status(self, goal_id: UUID, status: str) -> None:
        await self._db.execute(
            update(Goal).where(Goal.id == goal_id).values(status=status)
        )
        await self._db.commit()

    async def set_current_milestone(
        self,
        goal_id: UUID,
        milestone_id: UUID | None,
    ) -> None:
        await self._db.execute(
            update(Goal)
            .where(Goal.id == goal_id)
            .values(current_milestone_id=milestone_id)
        )
        await self._db.commit()
