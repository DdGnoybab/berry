"""Integration tests for WriteMdTool — real Postgres + real filesystem."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.material_repo import MaterialRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.workspace.paths import WorkspacePathError
from berry.assistants.learning.tools.workspace.write_md import WriteMdTool
from berry.core.db.repos.user_repo import UserRepo
from berry.core.tools.base import ToolContext


async def _seed(db_session: AsyncSession, suffix: str) -> tuple[UUID, UUID]:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"write_md_{suffix}",
        display_name="Write MD test",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    rows = await MilestoneRepo(db_session).insert_batch(g.id, [("ms", "")])
    return g.id, rows[0].id


def _ctx(db_session: AsyncSession, data_root: Path) -> ToolContext:
    return ToolContext(
        session_id=uuid4(),
        user_id=uuid4(),
        db=db_session,
        data_root=data_root,
    )


@pytest.mark.asyncio
async def test_write_md_creates_file_and_db_row(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    goal_id, ms_id = await _seed(db_session, "happy")
    tool = WriteMdTool()
    ctx = _ctx(db_session, tmp_path)

    raw = await tool.execute(
        {
            "goal_id": str(goal_id),
            "milestone_id": str(ms_id),
            "filename": "01-intro.md",
            "content": "# Intro\n\nHello world.",
            "source_url": "https://example.com/intro",
            "source_title": "Intro Source",
        },
        ctx,
    )
    payload = json.loads(raw)

    # File on disk
    file_path = (
        tmp_path / "goals" / str(goal_id) / "milestones" / str(ms_id) / "01-intro.md"
    )
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "# Intro\n\nHello world."

    # DB row
    material_id = UUID(payload["material_id"])
    material = await MaterialRepo(db_session).get_by_id(material_id)
    assert material is not None
    assert material.filename == "01-intro.md"
    assert material.size_bytes == len(b"# Intro\n\nHello world.")
    assert material.content_hash != ""
    assert material.source_url == "https://example.com/intro"
    assert material.source_title == "Intro Source"


@pytest.mark.asyncio
async def test_write_md_rejects_milestone_not_belonging_to_goal(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _, ms_id_a = await _seed(db_session, "scope_a")
    goal_id_b, _ = await _seed(db_session, "scope_b")

    tool = WriteMdTool()
    with pytest.raises(WorkspacePathError, match="does not belong"):
        await tool.execute(
            {
                "goal_id": str(goal_id_b),  # wrong goal
                "milestone_id": str(ms_id_a),
                "filename": "x.md",
                "content": "noop",
            },
            _ctx(db_session, tmp_path),
        )

    # Nothing written.
    assert not list(tmp_path.rglob("*.md"))


@pytest.mark.asyncio
async def test_write_md_rejects_nonexistent_milestone(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    goal_id, _ = await _seed(db_session, "ghost_ms")
    tool = WriteMdTool()
    with pytest.raises(WorkspacePathError, match="not found"):
        await tool.execute(
            {
                "goal_id": str(goal_id),
                "milestone_id": str(uuid4()),
                "filename": "x.md",
                "content": "noop",
            },
            _ctx(db_session, tmp_path),
        )


@pytest.mark.asyncio
async def test_write_md_rejects_unsafe_filename(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    goal_id, ms_id = await _seed(db_session, "unsafe_name")
    tool = WriteMdTool()
    for bad in ["../escape.md", ".hidden.md", "with space.md", "no-ext"]:
        with pytest.raises(WorkspacePathError):
            await tool.execute(
                {
                    "goal_id": str(goal_id),
                    "milestone_id": str(ms_id),
                    "filename": bad,
                    "content": "noop",
                },
                _ctx(db_session, tmp_path),
            )


@pytest.mark.asyncio
async def test_write_md_rejects_duplicate_filename(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    goal_id, ms_id = await _seed(db_session, "dup")
    tool = WriteMdTool()
    ctx = _ctx(db_session, tmp_path)

    args = {
        "goal_id": str(goal_id),
        "milestone_id": str(ms_id),
        "filename": "same.md",
        "content": "first",
    }
    await tool.execute(args, ctx)

    with pytest.raises(FileExistsError, match="already exists"):
        await tool.execute({**args, "content": "second"}, ctx)

    # First file's content unchanged.
    file_path = (
        tmp_path / "goals" / str(goal_id) / "milestones" / str(ms_id) / "same.md"
    )
    assert file_path.read_text(encoding="utf-8") == "first"


@pytest.mark.asyncio
async def test_write_md_orphan_cleanup_on_db_failure(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If MaterialRepo.insert raises after the file is written, the file
    should be deleted (no orphan).
    """
    goal_id, ms_id = await _seed(db_session, "orphan")
    tool = WriteMdTool()
    ctx = _ctx(db_session, tmp_path)

    async def _boom(self, **kwargs):
        raise RuntimeError("simulated DB failure after file write")

    monkeypatch.setattr(MaterialRepo, "insert", _boom)

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await tool.execute(
            {
                "goal_id": str(goal_id),
                "milestone_id": str(ms_id),
                "filename": "ghost.md",
                "content": "should be cleaned up",
            },
            ctx,
        )

    file_path = (
        tmp_path / "goals" / str(goal_id) / "milestones" / str(ms_id) / "ghost.md"
    )
    assert not file_path.exists(), "orphan file was not cleaned up"
