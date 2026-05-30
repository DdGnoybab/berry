"""Integration tests for MaterialRepo."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.material_repo import MaterialRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.core.db.repos.user_repo import UserRepo


async def _seed_milestone(db_session: AsyncSession, suffix: str) -> UUID:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"mat_test_{suffix}",
        display_name=f"Mat Test {suffix}",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    rows = await MilestoneRepo(db_session).insert_batch(g.id, [("ms", "")])
    return rows[0].id


@pytest.mark.asyncio
async def test_insert_persists_metadata(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "insert")
    repo = MaterialRepo(db_session)
    m = await repo.insert(
        milestone_id=mid,
        filename="01-intro.md",
        size_bytes=1024,
        content_hash="abc",
        source_url="https://example.com/intro",
        source_title="Intro",
        summary="An intro",
    )
    assert m.id is not None
    assert m.milestone_id == mid
    assert m.filename == "01-intro.md"
    assert m.source_url == "https://example.com/intro"
    assert m.summary == "An intro"
    assert m.size_bytes == 1024
    assert m.content_hash == "abc"


@pytest.mark.asyncio
async def test_unique_milestone_filename(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "unique")
    repo = MaterialRepo(db_session)
    await repo.insert(
        milestone_id=mid,
        filename="dup.md",
        size_bytes=10,
        content_hash="h1",
    )
    with pytest.raises(IntegrityError):
        await repo.insert(
            milestone_id=mid,
            filename="dup.md",
            size_bytes=20,
            content_hash="h2",
        )


@pytest.mark.asyncio
async def test_list_by_milestone_returns_all(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "listord")
    repo = MaterialRepo(db_session)
    await repo.insert(milestone_id=mid, filename="a.md", size_bytes=1, content_hash="h")
    await repo.insert(milestone_id=mid, filename="b.md", size_bytes=1, content_hash="h")

    rows = await repo.list_by_milestone(mid)
    assert {m.filename for m in rows} == {"a.md", "b.md"}


@pytest.mark.asyncio
async def test_update_after_edit(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "update")
    repo = MaterialRepo(db_session)
    m = await repo.insert(
        milestone_id=mid,
        filename="x.md",
        size_bytes=10,
        content_hash="orig",
    )
    await repo.update_after_edit(
        material_id=m.id,
        size_bytes=20,
        content_hash="new",
        summary="updated",
    )

    refreshed = await repo.get_by_id(m.id)
    assert refreshed is not None
    assert refreshed.size_bytes == 20
    assert refreshed.content_hash == "new"
    assert refreshed.summary == "updated"
