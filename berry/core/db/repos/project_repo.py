"""Repository for `projects`."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import Project


class ProjectRepo:
    """CRUD for the projects table."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: UUID,
        name: str,
        title: str,
        domain: str,
        workspace_path: str,
    ) -> Project:
        row = Project(
            user_id=user_id,
            name=name,
            title=title,
            domain=domain,
            workspace_path=workspace_path,
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def get_by_id(self, project_id: UUID) -> Project | None:
        result = await self._db.execute(
            select(Project).where(Project.id == project_id)  # type: ignore[arg-type]
        )
        return result.scalar_one_or_none()

    async def get_by_user_and_name(
        self, user_id: UUID, name: str
    ) -> Project | None:
        result = await self._db.execute(
            select(Project).where(
                Project.user_id == user_id,  # type: ignore[arg-type]
                Project.name == name,  # type: ignore[arg-type]
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: UUID) -> list[Project]:
        result = await self._db.execute(
            select(Project)
            .where(Project.user_id == user_id)  # type: ignore[arg-type]
            .order_by(Project.updated_at.desc())  # type: ignore[attr-defined]
        )
        return list(result.scalars().all())
