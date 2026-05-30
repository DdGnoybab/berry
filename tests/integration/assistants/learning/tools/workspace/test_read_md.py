"""Integration tests for ReadMdTool — depends on a previously written material."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.workspace.read_md import ReadMdTool
from berry.assistants.learning.tools.workspace.write_md import WriteMdTool
from berry.core.db.repos.user_repo import UserRepo
from berry.core.tools.base import ToolContext


def _ctx(db_session: AsyncSession, data_root: Path) -> ToolContext:
    return ToolContext(
        session_id=uuid4(),
        user_id=uuid4(),
        db=db_session,
        data_root=data_root,
    )


async def _seed_with_material(
    db_session: AsyncSession, tmp_path: Path, suffix: str, content: str = "hi"
) -> tuple[UUID, UUID, UUID]:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"read_md_{suffix}",
        display_name="Read MD test",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    rows = await MilestoneRepo(db_session).insert_batch(g.id, [("ms", "")])
    ms_id = rows[0].id

    raw = await WriteMdTool().execute(
        {
            "goal_id": str(g.id),
            "milestone_id": str(ms_id),
            "filename": "doc.md",
            "content": content,
            "source_url": "https://example.com/src",
        },
        _ctx(db_session, tmp_path),
    )
    material_id = UUID(json.loads(raw)["material_id"])
    return g.id, ms_id, material_id


@pytest.mark.asyncio
async def test_read_md_returns_full_content(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _, _, mid = await _seed_with_material(
        db_session, tmp_path, "happy", content="# Title\n\nbody."
    )
    raw = await ReadMdTool().execute(
        {"material_id": str(mid)}, _ctx(db_session, tmp_path)
    )
    payload = json.loads(raw)
    assert payload["filename"] == "doc.md"
    assert payload["content"] == "# Title\n\nbody."
    assert payload["source_url"] == "https://example.com/src"
    assert payload["truncated"] is False


@pytest.mark.asyncio
async def test_read_md_raises_for_unknown_material(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        await ReadMdTool().execute(
            {"material_id": str(uuid4())},
            _ctx(db_session, tmp_path),
        )


@pytest.mark.asyncio
async def test_read_md_truncates_oversized_content(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    huge = "x" * 60_000
    _, _, mid = await _seed_with_material(
        db_session, tmp_path, "huge", content=huge
    )
    raw = await ReadMdTool().execute(
        {"material_id": str(mid)}, _ctx(db_session, tmp_path)
    )
    payload = json.loads(raw)
    assert payload["truncated"] is True
    assert payload["content"].endswith("[truncated]")
