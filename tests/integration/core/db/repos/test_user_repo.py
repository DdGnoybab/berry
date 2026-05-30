"""Integration tests for UserRepo.

Uses local Postgres + alembic-applied schema (see tests/conftest.py).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.repos.user_repo import UserRepo


@pytest.mark.asyncio
async def test_create_or_get_creates_new_user(db_session: AsyncSession) -> None:
    repo = UserRepo(db_session)
    user = await repo.create_or_get_by_external(
        external_source="feishu",
        external_id="ou_test_create",
        display_name="Test Create",
    )
    assert user.id is not None
    assert user.external_source == "feishu"
    assert user.external_id == "ou_test_create"
    assert user.display_name == "Test Create"


@pytest.mark.asyncio
async def test_create_or_get_returns_existing_user(db_session: AsyncSession) -> None:
    """Calling twice with same (source, external_id) returns the same row."""
    repo = UserRepo(db_session)
    first = await repo.create_or_get_by_external(
        external_source="feishu",
        external_id="ou_test_idempotent",
        display_name="Original Name",
    )
    second = await repo.create_or_get_by_external(
        external_source="feishu",
        external_id="ou_test_idempotent",
        display_name="Updated Name",
    )
    assert first.id == second.id
    # display_name is updated on each call (so feishu rename propagates)
    assert second.display_name == "Updated Name"


@pytest.mark.asyncio
async def test_create_or_get_distinguishes_external_source(
    db_session: AsyncSession,
) -> None:
    """Same external_id under different sources are different users."""
    repo = UserRepo(db_session)
    feishu_user = await repo.create_or_get_by_external(
        external_source="feishu",
        external_id="overlap_id",
        display_name="Feishu User",
    )
    cli_user = await repo.create_or_get_by_external(
        external_source="cli",
        external_id="overlap_id",
        display_name="CLI User",
    )
    assert feishu_user.id != cli_user.id
