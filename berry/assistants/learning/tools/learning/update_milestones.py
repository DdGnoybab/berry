"""UpdateMilestonesTool — apply a batch of structural ops to milestones.

The LLM calls this when the user wants to revise the milestone plan
mid-way (e.g. "skip checkpointer, I already know it" / "add one for
sub-graphs after the conditional edges one"). All ops apply to the
user's currently-active goal — milestone_ids must belong to it.

Supported ops (one per array entry):
- insert {after_milestone_id|null, name, description}  — null = prepend
- delete {milestone_id}                                 — must not be active
- reorder {ordered_milestone_ids}                       — full permutation
- rename {milestone_id, name, description}
- skip   {milestone_id}                                 — sets status="skipped"

Ops execute in order; if any op fails, the change accumulated so far is
NOT rolled back (we don't open a single transaction across ops). This is
intentional — the LLM can re-issue remaining ops after seeing the partial
result. If you find this too lax in practice, wrap the body in a single
transaction and revisit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import select, update

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.core.db.models import Milestone
from berry.core.tools.base import ToolContext


class UpdateMilestonesTool:
    name: ClassVar[str] = "update_milestones"
    description: ClassVar[str] = (
        "Modify the active goal's milestones. Supported ops: insert (with "
        "after_milestone_id=null to prepend), delete (cannot delete the "
        "currently-active milestone), reorder (provide all milestone ids in "
        "the new order), rename, skip (marks as 'skipped' so the user can "
        "move past content they already know). Apply ops in array order."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "ops": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "enum": ["insert", "delete", "reorder", "rename", "skip"],
                        },
                        "after_milestone_id": {"type": ["string", "null"]},
                        "milestone_id": {"type": "string"},
                        "ordered_milestone_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["action"],
                },
            },
        },
        "required": ["ops"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.db is None:
            raise RuntimeError("update_milestones requires a db session in ToolContext")

        goal = await GoalRepo(ctx.db).get_active_for_user(ctx.user_id)
        if goal is None:
            raise ValueError(
                "no active goal — propose_goal_with_milestones first"
            )

        applied: list[dict[str, Any]] = []
        for op in args["ops"]:
            applied.append(await self._apply_one(op, goal.id, ctx))

        return json.dumps({"applied": applied}, ensure_ascii=False)

    async def _apply_one(
        self,
        op: dict[str, Any],
        goal_id: UUID,
        ctx: ToolContext,
    ) -> dict[str, Any]:
        assert ctx.db is not None
        action = op["action"]
        repo = MilestoneRepo(ctx.db)

        if action == "insert":
            return await self._do_insert(op, goal_id, repo, ctx)
        if action == "delete":
            return await self._do_delete(op, goal_id, ctx)
        if action == "reorder":
            return await self._do_reorder(op, goal_id, repo)
        if action == "rename":
            return await self._do_rename(op, goal_id, ctx)
        if action == "skip":
            return await self._do_skip(op, goal_id, ctx)
        raise ValueError(f"unknown action: {action!r}")

    async def _do_insert(
        self,
        op: dict[str, Any],
        goal_id: UUID,
        repo: MilestoneRepo,
        ctx: ToolContext,
    ) -> dict[str, Any]:
        name = str(op["name"])
        description = str(op["description"])
        after = op.get("after_milestone_id")

        # Strategy: append to end via append_one, then reorder if needed.
        new_row = await repo.append_one(goal_id, name=name, description=description)

        if after is not None:
            # Insert after a specific milestone — rebuild full order.
            existing = await repo.list_by_goal(goal_id)
            ids = [m.id for m in existing if m.id != new_row.id]
            target_after = UUID(after)
            try:
                idx_after = ids.index(target_after)
            except ValueError as exc:
                raise ValueError(
                    f"after_milestone_id {after} not in goal {goal_id}"
                ) from exc
            ids.insert(idx_after + 1, new_row.id)
            await repo.reorder(goal_id, ids)
            new_row = await _require_milestone(ctx, new_row.id)

        return {
            "action": "insert",
            "milestone_id": str(new_row.id),
            "order_index": new_row.order_index,
        }

    async def _do_delete(
        self,
        op: dict[str, Any],
        goal_id: UUID,
        ctx: ToolContext,
    ) -> dict[str, Any]:
        assert ctx.db is not None
        milestone_id = UUID(op["milestone_id"])
        target = await _require_milestone(ctx, milestone_id)
        if target.goal_id != goal_id:
            raise ValueError(
                f"milestone {milestone_id} does not belong to active goal {goal_id}"
            )
        if target.status == "active":
            raise ValueError(
                f"cannot delete milestone {milestone_id}: it's the active "
                "one. Move forward (mark_milestone_passed) or skip first."
            )

        # Use raw delete — MilestoneRepo doesn't expose a delete method;
        # this op is the only caller that needs it.
        from berry.core.db.models import Milestone as MilestoneModel

        await ctx.db.execute(
            MilestoneModel.__table__.delete().where(MilestoneModel.id == milestone_id)
        )
        await ctx.db.commit()
        return {"action": "delete", "milestone_id": str(milestone_id)}

    async def _do_reorder(
        self,
        op: dict[str, Any],
        goal_id: UUID,
        repo: MilestoneRepo,
    ) -> dict[str, Any]:
        ordered = [UUID(s) for s in op["ordered_milestone_ids"]]
        await repo.reorder(goal_id, ordered)
        return {"action": "reorder", "count": len(ordered)}

    async def _do_rename(
        self,
        op: dict[str, Any],
        goal_id: UUID,
        ctx: ToolContext,
    ) -> dict[str, Any]:
        assert ctx.db is not None
        milestone_id = UUID(op["milestone_id"])
        target = await _require_milestone(ctx, milestone_id)
        if target.goal_id != goal_id:
            raise ValueError(
                f"milestone {milestone_id} does not belong to active goal {goal_id}"
            )
        await ctx.db.execute(
            update(Milestone)
            .where(Milestone.id == milestone_id)
            .values(name=str(op["name"]), description=str(op["description"]))
        )
        await ctx.db.commit()
        return {"action": "rename", "milestone_id": str(milestone_id)}

    async def _do_skip(
        self,
        op: dict[str, Any],
        goal_id: UUID,
        ctx: ToolContext,
    ) -> dict[str, Any]:
        assert ctx.db is not None
        milestone_id = UUID(op["milestone_id"])
        target = await _require_milestone(ctx, milestone_id)
        if target.goal_id != goal_id:
            raise ValueError(
                f"milestone {milestone_id} does not belong to active goal {goal_id}"
            )
        await ctx.db.execute(
            update(Milestone)
            .where(Milestone.id == milestone_id)
            .values(status="skipped", passed_at=datetime.now(UTC))
        )
        await ctx.db.commit()
        return {"action": "skip", "milestone_id": str(milestone_id)}


async def _require_milestone(
    ctx: ToolContext, milestone_id: UUID
) -> Milestone:
    assert ctx.db is not None
    result = await ctx.db.execute(
        select(Milestone).where(Milestone.id == milestone_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError(f"milestone {milestone_id} not found")
    return row
