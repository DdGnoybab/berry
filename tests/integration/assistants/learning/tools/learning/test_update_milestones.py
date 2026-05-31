"""Integration tests for UpdateMilestonesTool — covers each op kind."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.learning.update_milestones import (
    UpdateMilestonesTool,
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


async def _seed_active_goal(
    db_session: AsyncSession, suffix: str, count: int = 3
) -> tuple[UUID, UUID, list[UUID]]:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"upd_{suffix}",
        display_name="Update MS Test",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    await GoalRepo(db_session).set_status(g.id, "active")
    rows = await MilestoneRepo(db_session).insert_batch(
        g.id, [(f"M{i}", f"d{i}") for i in range(count)]
    )
    return user.id, g.id, [r.id for r in rows]


@pytest.mark.asyncio
async def test_insert_at_end(db_session: AsyncSession, tmp_path: Path) -> None:
    user_id, goal_id, _ = await _seed_active_goal(db_session, "ins_end")
    raw = await UpdateMilestonesTool().execute(
        {
            "ops": [
                {
                    "action": "insert",
                    "name": "new_one",
                    "description": "d",
                }
            ]
        },
        _ctx(db_session, user_id, tmp_path),
    )
    applied = json.loads(raw)["applied"]
    assert applied[0]["action"] == "insert"
    assert applied[0]["order_index"] == 3  # appended after the 3 existing ones

    listed = await MilestoneRepo(db_session).list_by_goal(goal_id)
    assert listed[-1].name == "new_one"


@pytest.mark.asyncio
async def test_insert_after_id(db_session: AsyncSession, tmp_path: Path) -> None:
    user_id, goal_id, ms_ids = await _seed_active_goal(db_session, "ins_after")
    await UpdateMilestonesTool().execute(
        {
            "ops": [
                {
                    "action": "insert",
                    "after_milestone_id": str(ms_ids[0]),
                    "name": "between_0_and_1",
                    "description": "d",
                }
            ]
        },
        _ctx(db_session, user_id, tmp_path),
    )
    listed = await MilestoneRepo(db_session).list_by_goal(goal_id)
    assert [m.name for m in listed] == ["M0", "between_0_and_1", "M1", "M2"]


@pytest.mark.asyncio
async def test_skip_marks_skipped(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, goal_id, ms_ids = await _seed_active_goal(db_session, "skip")
    await UpdateMilestonesTool().execute(
        {"ops": [{"action": "skip", "milestone_id": str(ms_ids[1])}]},
        _ctx(db_session, user_id, tmp_path),
    )
    listed = await MilestoneRepo(db_session).list_by_goal(goal_id)
    target = next(m for m in listed if m.id == ms_ids[1])
    assert target.status == "skipped"
    assert target.passed_at is not None


@pytest.mark.asyncio
async def test_rename_updates_name_and_description(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, _goal_id, ms_ids = await _seed_active_goal(db_session, "rename")
    await UpdateMilestonesTool().execute(
        {
            "ops": [
                {
                    "action": "rename",
                    "milestone_id": str(ms_ids[0]),
                    "name": "renamed",
                    "description": "new description",
                }
            ]
        },
        _ctx(db_session, user_id, tmp_path),
    )
    refreshed = await MilestoneRepo(db_session).get_by_id(ms_ids[0])
    assert refreshed is not None
    assert refreshed.name == "renamed"
    assert refreshed.description == "new description"


@pytest.mark.asyncio
async def test_reorder(db_session: AsyncSession, tmp_path: Path) -> None:
    user_id, goal_id, ms_ids = await _seed_active_goal(db_session, "reord")
    new_order = [ms_ids[2], ms_ids[0], ms_ids[1]]
    await UpdateMilestonesTool().execute(
        {
            "ops": [
                {
                    "action": "reorder",
                    "ordered_milestone_ids": [str(i) for i in new_order],
                }
            ]
        },
        _ctx(db_session, user_id, tmp_path),
    )
    listed = await MilestoneRepo(db_session).list_by_goal(goal_id)
    assert [m.id for m in listed] == new_order


@pytest.mark.asyncio
async def test_delete(db_session: AsyncSession, tmp_path: Path) -> None:
    user_id, goal_id, ms_ids = await _seed_active_goal(db_session, "delete")
    await UpdateMilestonesTool().execute(
        {"ops": [{"action": "delete", "milestone_id": str(ms_ids[1])}]},
        _ctx(db_session, user_id, tmp_path),
    )
    listed = await MilestoneRepo(db_session).list_by_goal(goal_id)
    assert {m.id for m in listed} == {ms_ids[0], ms_ids[2]}


@pytest.mark.asyncio
async def test_no_active_goal_rejected(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id="upd_no_goal",
        display_name="x",
    )
    with pytest.raises(ValueError, match="no active goal"):
        await UpdateMilestonesTool().execute(
            {"ops": [{"action": "skip", "milestone_id": str(uuid4())}]},
            _ctx(db_session, user.id, tmp_path),
        )


@pytest.mark.asyncio
async def test_multiple_ops_in_order(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, goal_id, ms_ids = await _seed_active_goal(db_session, "multi")
    await UpdateMilestonesTool().execute(
        {
            "ops": [
                {"action": "skip", "milestone_id": str(ms_ids[0])},
                {
                    "action": "rename",
                    "milestone_id": str(ms_ids[1]),
                    "name": "renamed",
                    "description": "d",
                },
                {"action": "insert", "name": "appended", "description": "d"},
            ]
        },
        _ctx(db_session, user_id, tmp_path),
    )
    listed = await MilestoneRepo(db_session).list_by_goal(goal_id)
    assert listed[0].status == "skipped"
    assert listed[1].name == "renamed"
    assert listed[-1].name == "appended"
