"""Integration-style tests for document workflows using file tools.

Tests real-world document manipulation scenarios:
  1. Create a document with write_file
  2. Read it back with read_file
  3. Edit it with edit_file
  4. Verify the full round-trip

These tests exercise the tools together through the Tool.execute interface,
complementing the isolated unit tests in test_ops.py and test_read_tool.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from berry.core.tools.base import ToolContext
from berry.core.tools.files import (
    EditFileTool,
    ReadFileTool,
    WriteFileTool,
)
from berry.domain.errors import FileScopeError


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(
        session_id="doc-test",
        user_id=uuid4(),
        goal_id=None,
        db=None,
        data_root=cwd / ".data",
        cwd=cwd,
    )


@pytest.mark.asyncio
async def test_create_read_edit_roundtrip(tmp_path: Path) -> None:
    """Full document lifecycle: create -> read -> edit -> read again."""
    ctx = _ctx(tmp_path)

    # 1. Create a new document
    create_out = await WriteFileTool().execute(
        {"path": "notes/design.md", "content": "# Design Doc\n\nStatus: draft\n"},
        ctx,
    )
    created = json.loads(create_out)
    assert created["type"] == "create"
    assert (tmp_path / "notes" / "design.md").read_text() == "# Design Doc\n\nStatus: draft\n"

    # 2. Read it back
    read_out = await ReadFileTool().execute({"path": "notes/design.md"}, ctx)
    read_data = json.loads(read_out)
    assert read_data["type"] == "text"
    assert read_data["file"]["content"] == "# Design Doc\n\nStatus: draft"
    assert read_data["file"]["totalLines"] == 3

    # 3. Edit the status line
    edit_out = await EditFileTool().execute(
        {
            "path": "notes/design.md",
            "old_string": "Status: draft",
            "new_string": "Status: reviewed",
        },
        ctx,
    )
    edited = json.loads(edit_out)
    assert edited["replaceAll"] is False

    # 4. Read again to confirm the edit
    final_out = await ReadFileTool().execute({"path": "notes/design.md"}, ctx)
    final_data = json.loads(final_out)
    assert "reviewed" in final_data["file"]["content"]
    assert "draft" not in final_data["file"]["content"]


@pytest.mark.asyncio
async def test_write_overwrite_preserves_structure(tmp_path: Path) -> None:
    """Overwriting an existing file returns the original content."""
    ctx = _ctx(tmp_path)

    # Create initial version
    await WriteFileTool().execute(
        {"path": "config.yaml", "content": "debug: true\nport: 8080\n"},
        ctx,
    )

    # Overwrite
    out = await WriteFileTool().execute(
        {"path": "config.yaml", "content": "debug: false\nport: 9090\n"},
        ctx,
    )
    result = json.loads(out)
    assert result["type"] == "update"
    assert result["originalFile"] == "debug: true\nport: 8080\n"


@pytest.mark.asyncio
async def test_edit_with_offset_read_verification(tmp_path: Path) -> None:
    """Edit a file, then read with offset/limit to verify partial content."""
    ctx = _ctx(tmp_path)

    # Create a multi-line file
    lines = "\n".join(f"line {i}" for i in range(10))
    await WriteFileTool().execute(
        {"path": "data.txt", "content": lines + "\n"},
        ctx,
    )

    # Edit line 5 (index 4)
    await EditFileTool().execute(
        {
            "path": "data.txt",
            "old_string": "line 4",
            "new_string": "line FOUR",
        },
        ctx,
    )

    # Read only lines 3-6 (offset=2, limit=4)
    out = await ReadFileTool().execute(
        {"path": "data.txt", "offset": 2, "limit": 4},
        ctx,
    )
    result = json.loads(out)
    content_lines = result["file"]["content"].split("\n")
    assert "line FOUR" in content_lines
    assert result["file"]["startLine"] == 3
    assert result["file"]["numLines"] == 4


@pytest.mark.asyncio
async def test_nested_directory_document_workflow(tmp_path: Path) -> None:
    """Write/read/edit in deeply nested directories."""
    ctx = _ctx(tmp_path)

    path = "projects/2026/docs/notes.md"

    # Create in nested dir
    await WriteFileTool().execute(
        {"path": path, "content": "# Notes\n\n- item 1\n- item 2\n"},
        ctx,
    )

    # Read back
    out = await ReadFileTool().execute({"path": path}, ctx)
    data = json.loads(out)
    assert data["file"]["totalLines"] == 4

    # Add an item
    await EditFileTool().execute(
        {
            "path": path,
            "old_string": "- item 2",
            "new_string": "- item 2\n- item 3",
        },
        ctx,
    )

    # Verify
    final = json.loads(await ReadFileTool().execute({"path": path}, ctx))
    assert "- item 3" in final["file"]["content"]
    assert final["file"]["totalLines"] == 5


@pytest.mark.asyncio
async def test_document_scope_boundary_enforced(tmp_path: Path) -> None:
    """All three tools reject paths outside the workspace."""
    ctx = _ctx(tmp_path)
    outside = tmp_path.parent / "outside-doc-test"
    outside.mkdir(exist_ok=True)
    target = str(outside / "secret.md")

    # Write rejects
    with pytest.raises(FileScopeError):
        await WriteFileTool().execute(
            {"path": target, "content": "leaked"}, ctx,
        )

    # Create a file outside for read/edit to attempt
    (outside / "existing.md").write_text("data")

    # Read rejects
    with pytest.raises(FileScopeError):
        await ReadFileTool().execute({"path": str(outside / "existing.md")}, ctx)

    # Edit rejects
    with pytest.raises(FileScopeError):
        await EditFileTool().execute(
            {
                "path": str(outside / "existing.md"),
                "old_string": "data",
                "new_string": "hacked",
            },
            ctx,
        )
