"""Integration tests for MilestoneRepo, including the reorder negative-value trick."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.core.db.models import User
from berry.core.db.repos.user_repo import UserRepo


async def _seed_goal(db_session: AsyncSession, suffix: str) -> tuple[User, UUID]:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"ms_test_{suffix}",
        display_name=f"MS Test {suffix}",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id,
        title="t",
        workspace_path=f"goals/{suffix}",
    )
    return user, g.id


@pytest.mark.asyncio
async def test_insert_batch_assigns_order_indices(db_session: AsyncSession) -> None:
    _, gid = await _seed_goal(db_session, "batch")
    repo = MilestoneRepo(db_session)
    rows = await repo.insert_batch(
        gid,
        [("M1", "d1"), ("M2", "d2"), ("M3", "d3")],
    )
    assert [m.order_index for m in rows] == [0, 1, 2]
    assert [m.name for m in rows] == ["M1", "M2", "M3"]
    assert all(m.status == "pending" for m in rows)


@pytest.mark.asyncio
async def test_list_by_goal_returns_in_order(db_session: AsyncSession) -> None:
    _, gid = await _seed_goal(db_session, "list")
    repo = MilestoneRepo(db_session)
    await repo.insert_batch(gid, [("A", ""), ("B", ""), ("C", "")])

    rows = await repo.list_by_goal(gid)
    assert [m.name for m in rows] == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_set_status_passed(db_session: AsyncSession) -> None:
    _, gid = await _seed_goal(db_session, "passed")
    repo = MilestoneRepo(db_session)
    rows = await repo.insert_batch(gid, [("only", "")])
    await repo.set_status(rows[0].id, "passed")

    refreshed = await repo.get_by_id(rows[0].id)
    assert refreshed is not None
    assert refreshed.status == "passed"
    assert refreshed.passed_at is not None


@pytest.mark.asyncio
async def test_reorder_with_swap_does_not_violate_unique(
    db_session: AsyncSession,
) -> None:
    """Reorder must use temp-negative values inside one transaction so
    UniqueConstraint(goal_id, order_index) never trips on the swap.
    """
    _, gid = await _seed_goal(db_session, "reorder")
    repo = MilestoneRepo(db_session)
    rows = await repo.insert_batch(gid, [("A", ""), ("B", ""), ("C", "")])
    a, b, c = rows[0].id, rows[1].id, rows[2].id

    # New order: [C, A, B]
    await repo.reorder(gid, [c, a, b])

    after = await repo.list_by_goal(gid)
    assert [m.name for m in after] == ["C", "A", "B"]
    assert [m.order_index for m in after] == [0, 1, 2]


@pytest.mark.asyncio
async def test_reorder_rejects_id_set_mismatch(db_session: AsyncSession) -> None:
    _, gid = await _seed_goal(db_session, "mismatch")
    repo = MilestoneRepo(db_session)
    rows = await repo.insert_batch(gid, [("A", ""), ("B", "")])
    a = rows[0].id
    # Missing B
    with pytest.raises(ValueError, match="id set mismatch"):
        await repo.reorder(gid, [a])


@pytest.mark.asyncio
async def test_insert_after_existing_appends_to_end(db_session: AsyncSession) -> None:
    _, gid = await _seed_goal(db_session, "append")
    repo = MilestoneRepo(db_session)
    await repo.insert_batch(gid, [("A", ""), ("B", "")])
    new = await repo.append_one(gid, "C", "")
    assert new.order_index == 2
