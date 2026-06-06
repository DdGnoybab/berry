"""Tests for Memory system — store, tools, loader, extractor, consolidator."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from berry.core.tools.base import ToolContext
from berry.core.tools.memory.loader import (
    _keyword_fallback,
    _parse_indices,
    build_memory_injection,
    load_relevant_memories,
)
from berry.core.tools.memory.read import MemoryReadTool
from berry.core.tools.memory.store import MemoryEntry, MemoryStore, _slugify
from berry.core.tools.memory.write import MemoryWriteTool


# ── Helpers ──────────────────────────────────────────────────────────────


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(
        session_id="test-session",
        user_id=uuid4(),
        db=None,
        data_root=cwd,
        cwd=cwd,
    )


# ── MemoryStore ──────────────────────────────────────────────────────────


class TestMemoryStore:
    def test_write_and_read(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory")
        store.write("prefer-tabs", "user", "User prefers tabs", "Always use tabs.")
        entry = store.read("prefer-tabs")
        assert entry is not None
        assert entry.name == "prefer-tabs"
        assert entry.type == "user"
        assert entry.description == "User prefers tabs"
        assert "Always use tabs" in entry.body

    def test_write_creates_index(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory")
        store.write("test", "user", "Test desc", "Body")
        index = store.read_index()
        assert "test" in index
        assert "Test desc" in index

    def test_list_all_empty(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory")
        assert store.list_all() == []

    def test_list_all_sorted(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory")
        store.write("beta", "user", "B", "body")
        store.write("alpha", "user", "A", "body")
        entries = store.list_all()
        assert [e.name for e in entries] == ["alpha", "beta"]

    def test_delete(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory")
        store.write("to-delete", "user", "Delete me", "body")
        assert store.read("to-delete") is not None
        assert store.delete("to-delete") is True
        assert store.read("to-delete") is None

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory")
        assert store.delete("nope") is False

    def test_count(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory")
        assert store.count == 0
        store.write("a", "user", "A", "body")
        assert store.count == 1
        store.write("b", "feedback", "B", "body")
        assert store.count == 2

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory")
        store.write("item", "user", "V1", "body v1")
        store.write("item", "user", "V2", "body v2")
        entry = store.read("item")
        assert entry is not None
        assert entry.description == "V2"
        assert "body v2" in entry.body


# ── Slugify ──────────────────────────────────────────────────────────────


class TestSlugify:
    def test_basic(self) -> None:
        assert _slugify("User Prefer Tabs") == "user-prefer-tabs"

    def test_special_chars(self) -> None:
        assert _slugify("no@#$special!") == "nospecial"

    def test_empty(self) -> None:
        assert _slugify("") == "unnamed"

    def test_underscores(self) -> None:
        assert _slugify("some_name") == "some-name"


# ── MemoryEntry ──────────────────────────────────────────────────────────


class TestMemoryEntry:
    def test_valid_type(self) -> None:
        entry = MemoryEntry(name="x", type="user", description="d", body="b")
        assert entry.type == "user"

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid memory type"):
            MemoryEntry(name="x", type="invalid", description="d", body="b")


# ── Memory Tools ─────────────────────────────────────────────────────────


class TestMemoryWriteTool:
    @pytest.mark.asyncio
    async def test_write_and_read(self, tmp_path: Path) -> None:
        ctx = _ctx(tmp_path)
        write_tool = MemoryWriteTool()
        result = await write_tool.execute(
            {"name": "test", "type": "user", "description": "Test", "body": "Hello"},
            ctx,
        )
        assert "saved" in result.lower()

        read_tool = MemoryReadTool()
        result = await read_tool.execute({}, ctx)
        assert "test" in result
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_write_empty_name_errors(self, tmp_path: Path) -> None:
        write_tool = MemoryWriteTool()
        result = await write_tool.execute(
            {"name": "", "type": "user", "description": "x", "body": "y"},
            _ctx(tmp_path),
        )
        assert "error" in result.lower()


class TestMemoryReadTool:
    @pytest.mark.asyncio
    async def test_empty_store(self, tmp_path: Path) -> None:
        read_tool = MemoryReadTool()
        result = await read_tool.execute({}, _ctx(tmp_path))
        assert "no memories" in result.lower()


# ── Loader ───────────────────────────────────────────────────────────────


class TestLoader:
    def test_keyword_fallback_match(self) -> None:
        catalog = [
            MemoryEntry(name="prefer-tabs", type="user", description="User prefers tabs", body="", filename="prefer-tabs.md"),
            MemoryEntry(name="auth-rewrite", type="project", description="Auth rewrite project", body="", filename="auth-rewrite.md"),
        ]
        result = _keyword_fallback("please use tabs for this file", catalog)
        assert "prefer-tabs.md" in result

    def test_keyword_fallback_no_match(self) -> None:
        catalog = [
            MemoryEntry(name="prefer-tabs", type="user", description="User prefers tabs", body=""),
        ]
        result = _keyword_fallback("hello world", catalog)
        assert result == []

    def test_parse_indices_valid(self) -> None:
        assert _parse_indices("[0, 2]") == [0, 2]

    def test_parse_indices_empty(self) -> None:
        assert _parse_indices("[]") == []

    def test_parse_indices_no_json(self) -> None:
        assert _parse_indices("nothing") == []

    def test_build_memory_injection(self) -> None:
        entries = [
            MemoryEntry(name="tabs", type="user", description="Prefer tabs", body="Use tabs."),
        ]
        result = build_memory_injection(entries)
        assert "<system-reminder>" in result
        assert "tabs" in result
        assert "Use tabs." in result

    def test_build_memory_injection_empty(self) -> None:
        assert build_memory_injection([]) == ""

    def test_load_relevant_memories(self, tmp_path: Path) -> None:
        store = MemoryStore(tmp_path / "memory")
        store.write("test-mem", "user", "Test", "Content here")
        entries = load_relevant_memories(tmp_path / "memory", ["test-mem.md"])
        assert len(entries) == 1
        assert entries[0].name == "test-mem"
        assert "Content here" in entries[0].body

    def test_load_relevant_memories_nonexistent(self, tmp_path: Path) -> None:
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        entries = load_relevant_memories(mem_dir, ["nope.md"])
        assert entries == []
