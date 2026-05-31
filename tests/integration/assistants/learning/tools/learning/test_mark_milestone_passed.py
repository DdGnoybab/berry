"""Integration tests for MarkMilestonePassedTool — covers advance + completion."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.learning.mark_milestone_passed import (
    MarkMilestonePassedTool,
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


async def _seed_goal_with_milestones(
    db_session: AsyncSession, suffix: str, n: int
) -> tuple[UUID, UUID, list[UUID]]:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"mark_passed_{suffix}",
        display_name="Mark Passed Test",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    rows = await MilestoneRepo(db_session).insert_batch(
        g.id, [(f"M{i}", f"d{i}") for i in range(n)]
    )
    await GoalRepo(db_session).set_status(g.id, "active")
    await GoalRepo(db_session).set_current_milestone(g.id, rows[0].id)
    return user.id, g.id, [r.id for r in rows]


@pytest.mark.asyncio
async def test_advances_to_next_milestone(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, goal_id, ms_ids = await _seed_goal_with_milestones(db_session, "advance", 3)
    raw = await MarkMilestonePassedTool().execute(
        {"milestone_id": str(ms_ids[0])},
        _ctx(db_session, user_id, tmp_path),
    )
    payload = json.loads(raw)
    assert payload["milestone_status"] == "passed"
    assert payload["goal_status"] == "active"
    assert payload["next_milestone_id"] == str(ms_ids[1])

    # First milestone really got passed.
    first = await MilestoneRepo(db_session).get_by_id(ms_ids[0])
    assert first is not None
    assert first.status == "passed"
    assert first.passed_at is not None

    # Goal current_milestone_id moved.
    goal = await GoalRepo(db_session).get_by_id(goal_id)
    assert goal is not None
    assert goal.current_milestone_id == ms_ids[1]


@pytest.mark.asyncio
async def test_completes_goal_when_last_milestone(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, goal_id, ms_ids = await _seed_goal_with_milestones(db_session, "complete", 2)
    tool = MarkMilestonePassedTool()
    ctx = _ctx(db_session, user_id, tmp_path)

    await tool.execute({"milestone_id": str(ms_ids[0])}, ctx)
    raw = await tool.execute({"milestone_id": str(ms_ids[1])}, ctx)
    payload = json.loads(raw)

    assert payload["goal_status"] == "completed"
    assert payload["next_milestone_id"] is None

    goal = await GoalRepo(db_session).get_by_id(goal_id)
    assert goal is not None
    assert goal.status == "completed"
    assert goal.current_milestone_id is None


@pytest.mark.asyncio
async def test_unknown_milestone_raises(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, _, _ = await _seed_goal_with_milestones(db_session, "ghost", 1)
    with pytest.raises(ValueError, match="not found"):
        await MarkMilestonePassedTool().execute(
            {"milestone_id": str(uuid4())},
            _ctx(db_session, user_id, tmp_path),
        )


@pytest.mark.asyncio
async def test_skipped_milestones_do_not_advance_to(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """If the next-in-order milestone is already skipped, we should jump
    over it and stop at the next pending one. (Skipped = user said 'I know
    this'.) Not strictly required by spec but matches the user mental model.
    """
    user_id, _goal_id, ms_ids = await _seed_goal_with_milestones(db_session, "skip_jump", 3)

    # Manually set ms_ids[1] to skipped so passing ms_ids[0] should jump to ms_ids[2].
    from sqlalchemy import update

    from berry.core.db.models import Milestone

    await db_session.execute(
        update(Milestone).where(Milestone.id == ms_ids[1]).values(status="skipped")
    )
    await db_session.commit()

    raw = await MarkMilestonePassedTool().execute(
        {"milestone_id": str(ms_ids[0])},
        _ctx(db_session, user_id, tmp_path),
    )
    payload = json.loads(raw)
    assert payload["next_milestone_id"] == str(ms_ids[2])
