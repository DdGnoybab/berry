"""Integration tests for ListWorkspaceTool."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.core.db.repos.user_repo import UserRepo
from berry.core.tools.base import ToolContext
from berry.core.tools.workspace.list_workspace import ListWorkspaceTool
from berry.core.tools.workspace.write_md import WriteMdTool


def _ctx(db_session: AsyncSession, data_root: Path) -> ToolContext:
    return ToolContext(
        session_id=uuid4(),
        user_id=uuid4(),
        db=db_session,
        data_root=data_root,
    )


async def _seed(db_session: AsyncSession, suffix: str) -> tuple[UUID, UUID]:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"list_md_{suffix}",
        display_name="List Workspace test",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    rows = await MilestoneRepo(db_session).insert_batch(g.id, [("ms", "")])
    return g.id, rows[0].id


@pytest.mark.asyncio
async def test_list_returns_empty_for_fresh_milestone(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _, ms_id = await _seed(db_session, "empty")
    raw = await ListWorkspaceTool().execute(
        {"milestone_id": str(ms_id)}, _ctx(db_session, tmp_path)
    )
    assert json.loads(raw) == []


@pytest.mark.asyncio
async def test_list_returns_metadata_after_writes(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    goal_id, ms_id = await _seed(db_session, "after_writes")
    write = WriteMdTool()
    ctx = _ctx(db_session, tmp_path)

    for i, fname in enumerate(["01.md", "02.md"]):
        await write.execute(
            {
                "goal_id": str(goal_id),
                "milestone_id": str(ms_id),
                "filename": fname,
                "content": f"content {i}",
                "summary": f"summary {i}",
                "source_url": f"https://example.com/{i}",
            },
            ctx,
        )

    raw = await ListWorkspaceTool().execute(
        {"milestone_id": str(ms_id)}, ctx
    )
    items = json.loads(raw)
    assert len(items) == 2
    filenames = {item["filename"] for item in items}
    assert filenames == {"01.md", "02.md"}
    for item in items:
        assert "material_id" in item
        assert item["source_url"].startswith("https://example.com")
        assert item["summary"].startswith("summary")
        assert item["size_bytes"] > 0
