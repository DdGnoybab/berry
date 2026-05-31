"""Integration tests for ProposeGoalWithMilestonesTool."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.learning.propose_goal_with_milestones import (
    ProposeGoalWithMilestonesTool,
)
from berry.core.db.repos.user_repo import UserRepo
from berry.core.tools.base import ToolContext


def _ctx(db_session: AsyncSession, user_id: UUID, data_root: Path) -> ToolContext:
    return ToolContext(
        session_id=uuid4(),
        user_id=user_id,
        db=db_session,
        data_root=data_root,
    )


async def _make_user(db_session: AsyncSession, suffix: str) -> UUID:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"propose_goal_{suffix}",
        display_name="Propose Goal Test",
    )
    return user.id


@pytest.mark.asyncio
async def test_creates_goal_and_milestones(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id = await _make_user(db_session, "happy")
    raw = await ProposeGoalWithMilestonesTool().execute(
        {
            "title": "学 LangGraph",
            "milestones": [
                {"name": "M1", "description": "intro"},
                {"name": "M2", "description": "edges"},
                {"name": "M3", "description": "checkpointer"},
            ],
        },
        _ctx(db_session, user_id, tmp_path),
    )
    payload = json.loads(raw)

    goal_id = UUID(payload["goal_id"])
    goal = await GoalRepo(db_session).get_by_id(goal_id)
    assert goal is not None
    assert goal.title == "学 LangGraph"
    assert goal.status == "active"
    assert goal.user_id == user_id

    milestones = await MilestoneRepo(db_session).list_by_goal(goal_id)
    assert [m.name for m in milestones] == ["M1", "M2", "M3"]
    assert [m.order_index for m in milestones] == [0, 1, 2]
    assert all(m.status == "pending" for m in milestones)

    # current_milestone_id points to the first one
    refreshed = await GoalRepo(db_session).get_by_id(goal_id)
    assert refreshed is not None
    assert refreshed.current_milestone_id == milestones[0].id


@pytest.mark.asyncio
async def test_pauses_prior_active_goal(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id = await _make_user(db_session, "pause")
    tool = ProposeGoalWithMilestonesTool()
    ctx = _ctx(db_session, user_id, tmp_path)

    raw1 = await tool.execute(
        {
            "title": "first goal",
            "milestones": [
                {"name": "a", "description": "a"},
                {"name": "b", "description": "b"},
            ],
        },
        ctx,
    )
    first_goal_id = UUID(json.loads(raw1)["goal_id"])

    raw2 = await tool.execute(
        {
            "title": "second goal",
            "milestones": [
                {"name": "x", "description": "x"},
                {"name": "y", "description": "y"},
            ],
        },
        ctx,
    )
    second_payload = json.loads(raw2)

    assert second_payload["paused_prior_goal_id"] == str(first_goal_id)

    first = await GoalRepo(db_session).get_by_id(first_goal_id)
    assert first is not None
    assert first.status == "paused"

    second = await GoalRepo(db_session).get_by_id(UUID(second_payload["goal_id"]))
    assert second is not None
    assert second.status == "active"


@pytest.mark.asyncio
async def test_rejects_too_few_milestones(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id = await _make_user(db_session, "too_few")
    with pytest.raises((ValueError, Exception)):
        await ProposeGoalWithMilestonesTool().execute(
            {
                "title": "bad",
                "milestones": [{"name": "only one", "description": "x"}],
            },
            _ctx(db_session, user_id, tmp_path),
        )


@pytest.mark.asyncio
async def test_rejects_empty_title(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id = await _make_user(db_session, "no_title")
    with pytest.raises(ValueError, match="title"):
        await ProposeGoalWithMilestonesTool().execute(
            {
                "title": "   ",
                "milestones": [
                    {"name": "a", "description": "a"},
                    {"name": "b", "description": "b"},
                ],
            },
            _ctx(db_session, user_id, tmp_path),
        )
