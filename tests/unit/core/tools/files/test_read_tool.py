"""TDD tests for the three Tool wrappers.

The wrappers do three things:
  1. Declare claw-code-aligned name / description / input_schema.
  2. Pull args from the dict the runtime hands them.
  3. Call the matching ops.* function with ctx.cwd, json.dumps the dict.

Anything beyond that belongs in ops.py and is covered by test_ops.py.
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
        session_id="t1",
        user_id=uuid4(),
        goal_id=None,
        db=None,
        data_root=cwd / ".data",
        cwd=cwd,
    )


# ─── ReadFileTool ──────────────────────────────────────────────────────────


def test_read_tool_metadata_matches_clawcode() -> None:
    assert ReadFileTool.name == "read_file"
    assert ReadFileTool.description == "Read a text file from the workspace."
    schema = ReadFileTool.input_schema
    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert "offset" in schema["properties"]
    assert "limit" in schema["properties"]
    assert schema["required"] == ["path"]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_read_tool_returns_json_with_content(tmp_path: Path) -> None:
    (tmp_path / "x.md").write_text("hello\nworld\n")

    out = await ReadFileTool().execute({"path": "x.md"}, _ctx(tmp_path))
    parsed = json.loads(out)
    assert parsed["type"] == "text"
    assert parsed["file"]["content"] == "hello\nworld"
    assert parsed["file"]["totalLines"] == 2


@pytest.mark.asyncio
async def test_read_tool_propagates_offset_limit(tmp_path: Path) -> None:
    (tmp_path / "x.md").write_text("a\nb\nc\nd\n")

    out = await ReadFileTool().execute(
        {"path": "x.md", "offset": 1, "limit": 2}, _ctx(tmp_path),
    )
    parsed = json.loads(out)
    assert parsed["file"]["content"] == "b\nc"


@pytest.mark.asyncio
async def test_read_tool_propagates_scope_error(tmp_path: Path) -> None:
    outside = tmp_path.parent / "other-read-tool"
    outside.mkdir(exist_ok=True)
    (outside / "leak.md").write_text("x")

    with pytest.raises(FileScopeError):
        await ReadFileTool().execute(
            {"path": str(outside / "leak.md")}, _ctx(tmp_path),
        )


# ─── WriteFileTool ─────────────────────────────────────────────────────────


def test_write_tool_metadata_matches_clawcode() -> None:
    assert WriteFileTool.name == "write_file"
    assert WriteFileTool.description == "Write a text file in the workspace."
    schema = WriteFileTool.input_schema
    assert "path" in schema["properties"]
    assert "content" in schema["properties"]
    assert schema["required"] == ["path", "content"]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_write_tool_creates_file(tmp_path: Path) -> None:
    out = await WriteFileTool().execute(
        {"path": "new.md", "content": "hi"}, _ctx(tmp_path),
    )
    parsed = json.loads(out)

    assert parsed["type"] == "create"
    assert (tmp_path / "new.md").read_text() == "hi"


@pytest.mark.asyncio
async def test_write_tool_returns_update_for_existing_file(tmp_path: Path) -> None:
    (tmp_path / "x.md").write_text("old")
    out = await WriteFileTool().execute(
        {"path": "x.md", "content": "new"}, _ctx(tmp_path),
    )
    parsed = json.loads(out)

    assert parsed["type"] == "update"
    assert parsed["originalFile"] == "old"


# ─── EditFileTool ──────────────────────────────────────────────────────────


def test_edit_tool_metadata_matches_clawcode() -> None:
    assert EditFileTool.name == "edit_file"
    assert EditFileTool.description == "Replace text in a workspace file."
    schema = EditFileTool.input_schema
    assert "old_string" in schema["properties"]
    assert "new_string" in schema["properties"]
    assert "replace_all" in schema["properties"]
    assert schema["required"] == ["path", "old_string", "new_string"]


@pytest.mark.asyncio
async def test_edit_tool_replaces_unique_match(tmp_path: Path) -> None:
    file = tmp_path / "x.md"
    file.write_text("hello world\n")

    out = await EditFileTool().execute(
        {"path": "x.md", "old_string": "hello", "new_string": "hi"},
        _ctx(tmp_path),
    )
    parsed = json.loads(out)

    assert file.read_text() == "hi world\n"
    assert parsed["replaceAll"] is False


@pytest.mark.asyncio
async def test_edit_tool_replace_all_default_false(tmp_path: Path) -> None:
    """Spec § 11 ADR: missing replace_all means default False, multi-match rejected."""
    file = tmp_path / "x.md"
    file.write_text("foo\nfoo\n")

    with pytest.raises(ValueError, match="appears 2 times"):
        await EditFileTool().execute(
            {"path": "x.md", "old_string": "foo", "new_string": "bar"},
            _ctx(tmp_path),
        )


@pytest.mark.asyncio
async def test_edit_tool_replace_all_true(tmp_path: Path) -> None:
    file = tmp_path / "x.md"
    file.write_text("foo\nfoo\n")

    out = await EditFileTool().execute(
        {
            "path": "x.md",
            "old_string": "foo",
            "new_string": "bar",
            "replace_all": True,
        },
        _ctx(tmp_path),
    )
    parsed = json.loads(out)
    assert file.read_text() == "bar\nbar\n"
    assert parsed["replaceAll"] is True
