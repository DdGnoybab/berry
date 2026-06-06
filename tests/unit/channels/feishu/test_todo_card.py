"""todo_card.py 渲染器测试。"""

from __future__ import annotations

from berry.channels.feishu.todo_card import render_todo_card


class TestRenderTodoCard:
    def test_empty_todos(self) -> None:
        result = render_todo_card([])
        assert "清空" in result

    def test_all_pending(self) -> None:
        todos = [
            {"content": "Step 1", "activeForm": "Doing 1", "status": "pending"},
            {"content": "Step 2", "activeForm": "Doing 2", "status": "pending"},
        ]
        result = render_todo_card(todos)
        assert "0/2" in result
        assert "○ Step 1" in result
        assert "○ Step 2" in result

    def test_in_progress_shows_active_form(self) -> None:
        todos = [
            {"content": "Step 1", "activeForm": "正在重构", "status": "in_progress"},
        ]
        result = render_todo_card(todos)
        assert "**Step 1**" in result
        assert "正在重构" in result

    def test_completed_shows_strikethrough(self) -> None:
        todos = [
            {"content": "Step 1", "activeForm": "Done", "status": "completed"},
        ]
        result = render_todo_card(todos)
        assert "✅ ~~Step 1~~" in result

    def test_mixed_statuses(self) -> None:
        todos = [
            {"content": "A", "activeForm": "A", "status": "completed"},
            {"content": "B", "activeForm": "Working on B", "status": "in_progress"},
            {"content": "C", "activeForm": "C", "status": "pending"},
        ]
        result = render_todo_card(todos)
        assert "1/3" in result
        assert "✅ ~~A~~" in result
        assert "▸ **B** ← Working on B" in result
        assert "○ C" in result
