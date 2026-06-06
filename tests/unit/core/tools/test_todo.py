"""TodoWriteTool / TodoReadTool 测试。

对齐 claw-code 行为:验证、存储、verificationNudge、事件发射。
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from berry.core.tools.core.todo import (
    TodoReadTool,
    TodoWriteTool,
    _check_verification_nudge,
    _validate_todos,
)
from berry.core.tools.base import ToolContext


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(
        session_id="test-session",
        user_id=uuid4(),
        db=None,
        data_root=cwd,
        cwd=cwd,
    )


@pytest.fixture()
def ctx(tmp_path: Path) -> ToolContext:
    return _ctx(tmp_path)


@pytest.fixture()
def write_tool() -> TodoWriteTool:
    return TodoWriteTool()


@pytest.fixture()
def read_tool() -> TodoReadTool:
    return TodoReadTool()


# ---- validation ----


class TestValidation:
    def test_valid_todos_pass(self) -> None:
        todos = [
            {"content": "Do X", "activeForm": "Doing X", "status": "pending"},
            {"content": "Do Y", "activeForm": "Doing Y", "status": "in_progress"},
        ]
        assert _validate_todos(todos) is None

    def test_empty_content_fails(self) -> None:
        todos = [{"content": "", "activeForm": "Doing", "status": "pending"}]
        assert "content" in _validate_todos(todos)

    def test_empty_active_form_fails(self) -> None:
        todos = [{"content": "X", "activeForm": "", "status": "pending"}]
        assert "activeForm" in _validate_todos(todos)

    def test_invalid_status_fails(self) -> None:
        todos = [{"content": "X", "activeForm": "Y", "status": "done"}]
        assert "status" in _validate_todos(todos)


# ---- verification nudge ----


class TestVerificationNudge:
    def test_nudge_when_all_done_3_plus(self) -> None:
        todos = [
            {"content": "A", "activeForm": "A", "status": "completed"},
            {"content": "B", "activeForm": "B", "status": "completed"},
            {"content": "C", "activeForm": "C", "status": "completed"},
        ]
        assert _check_verification_nudge(todos) is True

    def test_no_nudge_when_less_than_3(self) -> None:
        todos = [
            {"content": "A", "activeForm": "A", "status": "completed"},
            {"content": "B", "activeForm": "B", "status": "completed"},
        ]
        assert _check_verification_nudge(todos) is False

    def test_no_nudge_when_has_verif(self) -> None:
        todos = [
            {"content": "A", "activeForm": "A", "status": "completed"},
            {"content": "B", "activeForm": "B", "status": "completed"},
            {"content": "verification step", "activeForm": "V", "status": "completed"},
        ]
        assert _check_verification_nudge(todos) is False

    def test_no_nudge_when_not_all_done(self) -> None:
        todos = [
            {"content": "A", "activeForm": "A", "status": "completed"},
            {"content": "B", "activeForm": "B", "status": "completed"},
            {"content": "C", "activeForm": "C", "status": "in_progress"},
        ]
        assert _check_verification_nudge(todos) is False


# ---- write tool ----


class TestTodoWriteTool:
    @pytest.mark.asyncio()
    async def test_write_todos(
        self, write_tool: TodoWriteTool, ctx: ToolContext, tmp_path: Path
    ) -> None:
        todos = [
            {"content": "Step 1", "activeForm": "Doing step 1", "status": "in_progress"},
            {"content": "Step 2", "activeForm": "Doing step 2", "status": "pending"},
        ]
        result = await write_tool.execute({"todos": todos}, ctx)

        assert "1 in progress" in result
        assert "1 pending" in result

        # Verify file written
        todo_file = tmp_path / ".berry" / "todos.json"
        assert todo_file.exists()
        saved = json.loads(todo_file.read_text())
        assert len(saved) == 2
        assert saved[0]["activeForm"] == "Doing step 1"

    @pytest.mark.asyncio()
    async def test_empty_list_returns_error(
        self, write_tool: TodoWriteTool, ctx: ToolContext
    ) -> None:
        result = await write_tool.execute({"todos": []}, ctx)
        assert "Error" in result

    @pytest.mark.asyncio()
    async def test_emits_event(
        self, write_tool: TodoWriteTool, ctx: ToolContext
    ) -> None:
        events = []
        from berry.core.agent.todo_event import register_todo_listener

        register_todo_listener(lambda e: events.append(e))

        todos = [{"content": "X", "activeForm": "X", "status": "pending"}]
        await write_tool.execute({"todos": todos}, ctx)

        assert len(events) == 1
        assert events[0].todos[0]["content"] == "X"


# ---- read tool ----


class TestTodoReadTool:
    @pytest.mark.asyncio()
    async def test_no_file_returns_message(
        self, read_tool: TodoReadTool, ctx: ToolContext
    ) -> None:
        result = await read_tool.execute({}, ctx)
        assert "No task list" in result

    @pytest.mark.asyncio()
    async def test_read_todos(
        self, read_tool: TodoReadTool, write_tool: TodoWriteTool, ctx: ToolContext
    ) -> None:
        todos = [
            {"content": "A", "activeForm": "Doing A", "status": "completed"},
            {"content": "B", "activeForm": "Doing B", "status": "in_progress"},
            {"content": "C", "activeForm": "Doing C", "status": "pending"},
        ]
        await write_tool.execute({"todos": todos}, ctx)
        result = await read_tool.execute({}, ctx)

        assert "✓" in result
        assert "▸" in result
        assert "○" in result
        assert "Doing B" in result
