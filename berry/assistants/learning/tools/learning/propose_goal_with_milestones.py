"""ProposeGoalWithMilestonesTool — create a Goal + ordered Milestones in one shot.

The LLM calls this after the user says what they want to learn AND after
some research (web_search / web_fetch) has informed the milestone breakdown.
The user approves once; the tool then:

1. Pauses any other active goal for this user (single-active-goal invariant).
2. Creates the Goal (status="active", workspace_path under data_root).
3. Bulk-inserts the milestones (order_index = 0..N-1, status="pending").
4. Sets goal.current_milestone_id to the first milestone.
5. Returns goal_id + milestone_ids so the LLM can reference them next turn.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from uuid import UUID

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.core.tools.base import ToolContext


class ProposeGoalWithMilestonesTool:
    name: ClassVar[str] = "propose_goal_with_milestones"
    description: ClassVar[str] = (
        "Create a NEW learning goal and split it into 2-10 ordered milestones "
        "in one approval-gated step. Use this exactly once per learning "
        "objective: after the user says what they want to learn AND after "
        "you've done a quick web_search to inform the breakdown. The first "
        "milestone is automatically marked as the current one."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": (
                    "The learning goal title, in the user's voice "
                    "(e.g. '学 LangGraph')."
                ),
            },
            "milestones": {
                "type": "array",
                "minItems": 2,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short milestone name (e.g. '理解 StateGraph 概念').",
                        },
                        "description": {
                            "type": "string",
                            "description": (
                                "What the user should be able to do after this "
                                "milestone (1-2 sentences)."
                            ),
                        },
                    },
                    "required": ["name", "description"],
                },
                "description": "Milestones in priority order (easiest / earliest first).",
            },
        },
        "required": ["title", "milestones"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.db is None:
            raise RuntimeError("propose_goal_with_milestones requires a db session in ToolContext")

        title = str(args["title"]).strip()
        if not title:
            raise ValueError("title must be non-empty")
        milestones_raw = list(args["milestones"])
        if not 2 <= len(milestones_raw) <= 10:
            raise ValueError(
                f"milestones must have 2-10 entries, got {len(milestones_raw)}"
            )
        items = [
            (str(m["name"]).strip(), str(m["description"]).strip())
            for m in milestones_raw
        ]
        for i, (name, _) in enumerate(items):
            if not name:
                raise ValueError(f"milestone[{i}].name must be non-empty")

        goal_repo = GoalRepo(ctx.db)
        milestone_repo = MilestoneRepo(ctx.db)

        # 1. Pause any prior active goal for this user — single-active invariant.
        prior = await goal_repo.get_active_for_user(ctx.user_id)
        if prior is not None:
            await goal_repo.set_status(prior.id, "paused")

        # 2. Create the new goal (active).
        goal = await goal_repo.create(
            user_id=ctx.user_id,
            title=title,
            workspace_path=f"goals/{ctx.user_id}",
            domain="learning",
        )
        await goal_repo.set_status(goal.id, "active")

        # 3. Bulk-insert milestones.
        inserted = await milestone_repo.insert_batch(goal.id, items)

        # 4. Set the current milestone to the first one.
        first_milestone_id: UUID = inserted[0].id
        await goal_repo.set_current_milestone(goal.id, first_milestone_id)

        return json.dumps(
            {
                "goal_id": str(goal.id),
                "current_milestone_id": str(first_milestone_id),
                "milestone_ids": [str(m.id) for m in inserted],
                "paused_prior_goal_id": str(prior.id) if prior is not None else None,
            },
            ensure_ascii=False,
        )
