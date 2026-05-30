"""Integration tests for GoalRepo (uses real Postgres via conftest)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.core.db.models import User
from berry.core.db.repos.user_repo import UserRepo


async def _make_user(db_session: AsyncSession, suffix: str) -> User:
    return await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"goal_test_{suffix}",
        display_name=f"Goal Test {suffix}",
    )


@pytest.mark.asyncio
async def test_create_goal_persists_basic_fields(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "create")
    repo = GoalRepo(db_session)
    g = await repo.create(
        user_id=user.id,
        title="学 LangGraph",
        workspace_path="goals/abc",
    )
    assert g.id is not None
    assert g.user_id == user.id
    assert g.domain == "learning"
    assert g.title == "学 LangGraph"
    assert g.status == "drafting"
    assert g.workspace_path == "goals/abc"
    assert g.current_milestone_id is None


@pytest.mark.asyncio
async def test_get_active_for_user_returns_none_when_no_active(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, "no_active")
    repo = GoalRepo(db_session)
    assert await repo.get_active_for_user(user.id) is None


@pytest.mark.asyncio
async def test_get_active_for_user_returns_active_goal(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, "has_active")
    repo = GoalRepo(db_session)
    g = await repo.create(
        user_id=user.id,
        title="x",
        workspace_path="goals/x",
    )
    await repo.set_status(g.id, "active")

    found = await repo.get_active_for_user(user.id)
    assert found is not None
    assert found.id == g.id
    assert found.status == "active"


@pytest.mark.asyncio
async def test_set_current_milestone_id(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "current_ms")
    repo = GoalRepo(db_session)
    g = await repo.create(user_id=user.id, title="t", workspace_path="goals/cm")

    # We need a milestone first so the FK validates. Insert via raw SQL to keep
    # this test focused on goal_repo (full milestone tests are in test_milestone_repo).
    from sqlalchemy import text
    result = await db_session.execute(
        text(
            "INSERT INTO milestones (goal_id, order_index, name, description) "
            "VALUES (:gid, 0, 'm', 'd') RETURNING id"
        ),
        {"gid": str(g.id)},
    )
    ms_id = result.scalar_one()
    await db_session.commit()

    await repo.set_current_milestone(g.id, ms_id)
    refreshed = await repo.get_by_id(g.id)
    assert refreshed is not None
    assert refreshed.current_milestone_id == ms_id


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing(db_session: AsyncSession) -> None:
    from uuid import uuid4
    repo = GoalRepo(db_session)
    assert await repo.get_by_id(uuid4()) is None
