"""TodoWriteTool / TodoReadTool — session-level task tracking.

对齐 claw-code TodoWrite:
- 数据结构:{content, activeForm, status}
- 验证:拒空 content / 空 activeForm / 非法 status
- 存储:.berry/todos.json (JSON)
- 返回:摘要 + verificationNudge
- 全完成:写空数组清空

berry 扩展:emit TodoUpdatedEvent 通知飞书渲染。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext

_VALID_STATUSES = ("pending", "in_progress", "completed")


class TodoWriteTool:
    """Create or update a structured task list for tracking progress."""

    name: ClassVar[str] = "todo_write"
    description: ClassVar[str] = (
        "Create or update a structured task list for tracking progress. "
        "Use this to plan and track multi-step work."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Brief task description.",
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "What you are doing for this task.",
                        },
                        "status": {
                            "type": "string",
                            "enum": list(_VALID_STATUSES),
                        },
                    },
                    "required": ["content", "activeForm", "status"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["todos"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        todos = args.get("todos", [])

        if not todos:
            return "Error: todos list must not be empty"

        # Validate
        error = _validate_todos(todos)
        if error:
            return error

        # Read old todos before overwriting
        old_todos = _read_todos(ctx.cwd)

        # Write — whole-array replacement, same as claw-code:
        # LLM sends the full list, tool persists it as-is.
        todo_path = _todo_store_path(ctx.cwd)
        todo_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            todo_path.write_text(
                json.dumps(todos, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            return f"Error: cannot write todo file: {exc}"

        # Verification nudge (对齐 claw-code)
        nudge = _check_verification_nudge(todos)

        # Emit event (berry extension — 飞书渲染)
        _emit_event(ctx, todos, old_todos, nudge)

        return _build_summary(todos, nudge)


class TodoReadTool:
    """Read the current task list to check progress."""

    name: ClassVar[str] = "todo_read"
    description: ClassVar[str] = "Read the current task list to check progress."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        todos = _read_todos(ctx.cwd)

        if not todos:
            return "No task list exists yet."

        lines: list[str] = []
        for i, todo in enumerate(todos, 1):
            status = todo.get("status", "pending")
            marker = {"pending": "○", "in_progress": "▸", "completed": "✓"}[status]
            active = " ← " + todo["activeForm"] if status == "in_progress" else ""
            lines.append(f"  [{marker}] {i}. {todo['content']}{active}")

        return "\n".join(lines)


# ---- helpers ----


def _validate_todos(todos: list[dict[str, Any]]) -> str | None:
    """Validate todo items. Returns error message or None."""
    for i, todo in enumerate(todos):
        if not todo.get("content", "").strip():
            return f"Error: todo[{i}].content must not be empty"
        if not todo.get("activeForm", "").strip():
            return f"Error: todo[{i}].activeForm must not be empty"
        if todo.get("status") not in _VALID_STATUSES:
            return f"Error: todo[{i}].status must be {'/'.join(_VALID_STATUSES)}"
    return None


def _check_verification_nudge(todos: list[dict[str, Any]]) -> bool:
    """All done + ≥3 items + none contain 'verif' → nudge needed."""
    all_done = all(t["status"] == "completed" for t in todos)
    if not all_done or len(todos) < 3:
        return False
    return not any("verif" in t["content"].lower() for t in todos)


def _build_summary(todos: list[dict[str, Any]], nudge: bool) -> str:
    pending = sum(1 for t in todos if t["status"] == "pending")
    in_progress = sum(1 for t in todos if t["status"] == "in_progress")
    completed = sum(1 for t in todos if t["status"] == "completed")

    parts = [
        f"Updated: {completed} done, {in_progress} in progress, {pending} pending ({len(todos)} total)"
    ]
    if nudge:
        parts.append(
            "All tasks complete. Consider verifying your work before finishing."
        )
    return "\n".join(parts)


def _read_todos(cwd: Path) -> list[dict[str, Any]]:
    """Read existing todos from disk. Returns empty list if not found."""
    todo_path = _todo_store_path(cwd)
    if not todo_path.is_file():
        return []
    try:
        content = todo_path.read_text(encoding="utf-8")
        return json.loads(content) or []
    except (OSError, json.JSONDecodeError):
        return []


def _emit_event(
    ctx: ToolContext,
    todos: list[dict[str, Any]],
    old_todos: list[dict[str, Any]],
    nudge: bool,
) -> None:
    """Fire-and-forget event emission. Import here to avoid circular dep at module level."""
    try:
        from berry.core.agent.todo_event import TodoUpdatedEvent, emit_todo_updated

        emit_todo_updated(
            TodoUpdatedEvent(
                conversation_id=ctx.session_id,
                todos=todos,
                old_todos=old_todos,
                verification_nudge=nudge,
            )
        )
    except Exception:
        pass  # rendering failure must not block the tool


def _todo_store_path(cwd: Path) -> Path:
    """Path to the todo JSON file in the workspace."""
    return cwd / ".berry" / "todos.json"
