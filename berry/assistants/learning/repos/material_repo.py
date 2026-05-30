"""Repository for the `materials` table.

Reminder: file system is the source of truth for content; this row is metadata.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import Material


class MaterialRepo:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def insert(
        self,
        *,
        milestone_id: UUID,
        filename: str,
        size_bytes: int,
        content_hash: str,
        source_url: str | None = None,
        source_title: str | None = None,
        summary: str | None = None,
    ) -> Material:
        """Insert a new material metadata row.

        Args:
            milestone_id: The milestone this material belongs to.
            filename: The .md filename (unique per milestone).
            size_bytes: Size of the file in bytes.
            content_hash: Hash of the file contents for change detection.
            source_url: Optional URL the material was sourced from.
            source_title: Optional human-readable title of the source.
            summary: Optional short summary of the material content.

        Returns:
            The newly created and refreshed Material row.
        """
        row = Material(
            milestone_id=milestone_id,
            filename=filename,
            size_bytes=size_bytes,
            content_hash=content_hash,
            source_url=source_url,
            source_title=source_title,
            summary=summary,
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def get_by_id(self, material_id: UUID) -> Material | None:
        """Fetch a single material by primary key.

        Args:
            material_id: The UUID primary key.

        Returns:
            The Material row, or None if not found.
        """
        result = await self._db.execute(
            select(Material).where(Material.id == material_id)
        )
        return result.scalar_one_or_none()

    async def get_by_milestone_filename(
        self,
        milestone_id: UUID,
        filename: str,
    ) -> Material | None:
        """Fetch a material by its (milestone, filename) UNIQUE pair.

        Used by write_md to pre-check uniqueness before writing the file —
        catching the conflict in Python is cleaner than letting the DB raise
        IntegrityError mid-write.
        """
        result = await self._db.execute(
            select(Material).where(
                Material.milestone_id == milestone_id,
                Material.filename == filename,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_milestone(self, milestone_id: UUID) -> list[Material]:
        """Return all materials for a milestone ordered by created_at, then id.

        Args:
            milestone_id: The milestone whose materials to list.

        Returns:
            List of Material rows in insertion order.
        """
        result = await self._db.execute(
            select(Material)
            .where(Material.milestone_id == milestone_id)
            .order_by(Material.created_at.asc(), Material.id.asc())
        )
        return list(result.scalars().all())

    async def update_after_edit(
        self,
        *,
        material_id: UUID,
        size_bytes: int,
        content_hash: str,
        summary: str | None = None,
    ) -> None:
        """Update metadata after the underlying .md file has been edited.

        Only updates summary if provided (non-None), so callers that don't
        touch the summary can omit it without clearing the existing value.

        Args:
            material_id: The UUID of the material to update.
            size_bytes: New file size in bytes.
            content_hash: New content hash.
            summary: If provided, replaces the existing summary.
        """
        values: dict[str, object] = {
            "size_bytes": size_bytes,
            "content_hash": content_hash,
        }
        if summary is not None:
            values["summary"] = summary
        await self._db.execute(
            update(Material).where(Material.id == material_id).values(**values)
        )
        await self._db.commit()
