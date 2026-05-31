"""MarkMilestonePassedTool — close out the current milestone, move on.

Walks the goal forward:
1. Mark the named milestone as passed (status="passed", passed_at=now).
2. Advance goal.current_milestone_id to the next pending/skipped milestone
   in order_index order. If none remain, mark the goal completed
   (status="completed", current_milestone_id=null).

Approval-gated: per Q4 brainstorm, the LLM interprets user's natural
language ("下一题", "next") and proposes this call; the user still gets
to confirm via [y/N] so a misread doesn't silently skip ahead.
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


class MarkMilestonePassedTool:
    name: ClassVar[str] = "mark_milestone_passed"
    description: ClassVar[str] = (
        "Mark the given milestone as passed and advance the goal's "
        "current_milestone_id to the next pending milestone (or mark the "
        "goal completed if this was the last). Use this when the user "
        "explicitly signals they're done with the current milestone "
        "(e.g. 'next', '下一个', 'I'm good with this one')."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "milestone_id": {
                "type": "string",
                "description": (
                    "UUID of the milestone to mark passed (usually the "
                    "current_milestone_id from the system prompt)."
                ),
            },
        },
        "required": ["milestone_id"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.db is None:
            raise RuntimeError("mark_milestone_passed requires a db session in ToolContext")

        milestone_id = UUID(str(args["milestone_id"]))
        repo = MilestoneRepo(ctx.db)
        target = await repo.get_by_id(milestone_id)
        if target is None:
            raise ValueError(f"milestone {milestone_id} not found")

        # 1. Mark passed.
        await ctx.db.execute(
            update(Milestone)
            .where(Milestone.id == milestone_id)
            .values(status="passed", passed_at=datetime.now(UTC))
        )
        await ctx.db.commit()

        # 2. Find next milestone in this goal that is still pending.
        result = await ctx.db.execute(
            select(Milestone)
            .where(
                Milestone.goal_id == target.goal_id,
                Milestone.status == "pending",
            )
            .order_by(Milestone.order_index.asc())
            .limit(1)
        )
        next_row = result.scalar_one_or_none()

        goal_repo = GoalRepo(ctx.db)
        if next_row is None:
            # No more pending milestones — goal completed.
            await goal_repo.set_current_milestone(target.goal_id, None)
            await goal_repo.set_status(target.goal_id, "completed")
            return json.dumps(
                {
                    "milestone_id": str(milestone_id),
                    "milestone_status": "passed",
                    "goal_status": "completed",
                    "next_milestone_id": None,
                },
                ensure_ascii=False,
            )

        await goal_repo.set_current_milestone(target.goal_id, next_row.id)
        return json.dumps(
            {
                "milestone_id": str(milestone_id),
                "milestone_status": "passed",
                "goal_status": "active",
                "next_milestone_id": str(next_row.id),
                "next_milestone_name": next_row.name,
            },
            ensure_ascii=False,
        )
