"""Repository for the `milestones` table.

The reorder method demonstrates the spec §八.8.2 "temporary negative value"
pattern: the UniqueConstraint(goal_id, order_index) trips on naive
in-place updates because two rows can't simultaneously hold the same index
during a multi-row swap. Solution: in one transaction, push every affected
row to a unique negative index, then write the target indices.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import Milestone


class MilestoneRepo:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def insert_batch(
        self,
        goal_id: UUID,
        items: list[tuple[str, str]],
    ) -> list[Milestone]:
        """Bulk-insert milestones for a goal. order_index is 0..N in input order.

        Each item is (name, description).
        """
        rows = [
            Milestone(
                goal_id=goal_id,
                order_index=i,
                name=name,
                description=desc,
                status="pending",
            )
            for i, (name, desc) in enumerate(items)
        ]
        self._db.add_all(rows)
        await self._db.commit()
        for r in rows:
            await self._db.refresh(r)
        return rows

    async def list_by_goal(self, goal_id: UUID) -> list[Milestone]:
        """Return all milestones for a goal ordered by order_index ascending."""
        result = await self._db.execute(
            select(Milestone)
            .where(Milestone.goal_id == goal_id)
            .order_by(Milestone.order_index.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, milestone_id: UUID) -> Milestone | None:
        """Fetch a single milestone by primary key."""
        result = await self._db.execute(
            select(Milestone).where(Milestone.id == milestone_id)
        )
        return result.scalar_one_or_none()

    async def set_status(self, milestone_id: UUID, status: str) -> None:
        """Update the status of a milestone; records passed_at when status="passed"."""
        values: dict[str, object] = {"status": status}
        if status == "passed":
            values["passed_at"] = datetime.now(UTC)
        await self._db.execute(
            update(Milestone).where(Milestone.id == milestone_id).values(**values)
        )
        await self._db.commit()

    async def append_one(
        self,
        goal_id: UUID,
        name: str,
        description: str,
    ) -> Milestone:
        """Insert one milestone at the end (order_index = current max + 1).

        If the goal has no milestones yet, COALESCE maps NULL → -1, so
        next_idx = 0 (correct first entry).
        """
        max_result = await self._db.execute(
            select(func.coalesce(func.max(Milestone.order_index), -1)).where(
                Milestone.goal_id == goal_id
            )
        )
        next_idx = int(max_result.scalar_one()) + 1
        row = Milestone(
            goal_id=goal_id,
            order_index=next_idx,
            name=name,
            description=description,
            status="pending",
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def reorder(self, goal_id: UUID, ordered_ids: list[UUID]) -> None:
        """Apply a new total order. `ordered_ids` MUST be a permutation of the
        current milestone ids for this goal.

        Strategy (spec §八.8.2):
          1. In one transaction, set every affected row's order_index to a
             unique negative value (-(i+1)). Negatives can never collide with
             positive existing values nor with each other.
          2. Then set them to target positives 0..N-1.
        Both steps run inside the same transaction so UniqueConstraint never
        sees an inconsistent state.

        Raises:
            ValueError: if ordered_ids is not a permutation of the goal's
                current milestone ids.
        """
        existing = await self.list_by_goal(goal_id)
        existing_ids = {m.id for m in existing}
        if existing_ids != set(ordered_ids):
            raise ValueError(
                f"reorder id set mismatch: have {existing_ids}, got {set(ordered_ids)}"
            )

        # Phase 1: push every row to a unique negative index keyed by current position.
        # -(i+1) guarantees uniqueness and avoids 0 (which is a valid positive target).
        negative_cases = case(
            *[
                (Milestone.id == m.id, -(i + 1))
                for i, m in enumerate(existing)
            ],
            else_=Milestone.order_index,
        )
        await self._db.execute(
            update(Milestone)
            .where(Milestone.goal_id == goal_id)
            .values(order_index=negative_cases)
        )

        # Phase 2: write the target positive indices from the requested order.
        positive_cases = case(
            *[
                (Milestone.id == mid, i)
                for i, mid in enumerate(ordered_ids)
            ],
            else_=Milestone.order_index,
        )
        await self._db.execute(
            update(Milestone)
            .where(Milestone.goal_id == goal_id)
            .values(order_index=positive_cases)
        )
        await self._db.commit()
