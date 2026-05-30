"""Integration tests for EditMdTool — old_string uniqueness + rollback."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.material_repo import MaterialRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.workspace.edit_md import EditMdTool
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
    db_session: AsyncSession, tmp_path: Path, suffix: str, content: str
) -> tuple[UUID, UUID, UUID]:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"edit_md_{suffix}",
        display_name="Edit MD test",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    rows = await MilestoneRepo(db_session).insert_batch(g.id, [("ms", "")])
    raw = await WriteMdTool().execute(
        {
            "goal_id": str(g.id),
            "milestone_id": str(rows[0].id),
            "filename": "doc.md",
            "content": content,
        },
        _ctx(db_session, tmp_path),
    )
    return g.id, rows[0].id, UUID(json.loads(raw)["material_id"])


@pytest.mark.asyncio
async def test_edit_replaces_unique_substring(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _, _, mid = await _seed_with_material(
        db_session, tmp_path, "happy",
        content="# Title\n\nThe quick brown fox.\n",
    )
    raw = await EditMdTool().execute(
        {
            "material_id": str(mid),
            "old_string": "quick brown fox",
            "new_string": "lazy dog",
        },
        _ctx(db_session, tmp_path),
    )
    payload = json.loads(raw)
    assert payload["filename"] == "doc.md"
    assert payload["new_size"] != payload["old_size"]

    # File on disk reflects the edit. We rglob doc.md to avoid hard-coding
    # the goal_id / milestone_id path components.
    material = await MaterialRepo(db_session).get_by_id(mid)
    assert material is not None
    found = list(tmp_path.rglob("doc.md"))
    assert len(found) == 1
    assert found[0].read_text(encoding="utf-8") == "# Title\n\nThe lazy dog.\n"


@pytest.mark.asyncio
async def test_edit_rejects_old_string_not_found(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _, _, mid = await _seed_with_material(
        db_session, tmp_path, "missing", content="hello"
    )
    with pytest.raises(ValueError, match="not found"):
        await EditMdTool().execute(
            {
                "material_id": str(mid),
                "old_string": "world",
                "new_string": "x",
            },
            _ctx(db_session, tmp_path),
        )


@pytest.mark.asyncio
async def test_edit_rejects_old_string_appearing_multiple_times(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _, _, mid = await _seed_with_material(
        db_session, tmp_path, "ambig",
        content="x = 1\ny = x + x\nz = x\n",
    )
    with pytest.raises(ValueError, match=r"appears \d+ times"):
        await EditMdTool().execute(
            {
                "material_id": str(mid),
                "old_string": "x",
                "new_string": "X",
            },
            _ctx(db_session, tmp_path),
        )


@pytest.mark.asyncio
async def test_edit_restores_file_on_db_update_failure(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, mid = await _seed_with_material(
        db_session, tmp_path, "rollback", content="orig content"
    )

    async def _boom(self, **kwargs):
        raise RuntimeError("simulated DB failure after file write")

    monkeypatch.setattr(MaterialRepo, "update_after_edit", _boom)

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await EditMdTool().execute(
            {
                "material_id": str(mid),
                "old_string": "orig",
                "new_string": "NEW",
            },
            _ctx(db_session, tmp_path),
        )

    # File should be restored to original content.
    found = list(tmp_path.rglob("doc.md"))
    assert len(found) == 1
    assert found[0].read_text(encoding="utf-8") == "orig content"


@pytest.mark.asyncio
async def test_edit_rejects_empty_old_string(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    _, _, mid = await _seed_with_material(
        db_session, tmp_path, "empty", content="x"
    )
    with pytest.raises(ValueError, match="non-empty"):
        await EditMdTool().execute(
            {
                "material_id": str(mid),
                "old_string": "",
                "new_string": "y",
            },
            _ctx(db_session, tmp_path),
        )
