"""TodoWriteTool — session-level task tracking.

Mirrors claw-code's TodoWrite tool. Maintains a structured task list
that the LLM uses to track progress through multi-step work (skill
checklists, implementation plans, etc).

State is stored as a JSON file in the session directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext


class TodoWriteTool:
    """Update the structured task list for the current session."""

    name: ClassVar[str] = "todo_write"
    description: ClassVar[str] = (
        "Create or update a structured task list for tracking progress. "
        "Use this to track multi-step work like skill checklists or plans."
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
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["content", "status"],
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
        for i, todo in enumerate(todos):
            if not todo.get("content", "").strip():
                return f"Error: todo[{i}].content must not be empty"
            if todo.get("status") not in ("pending", "in_progress", "completed"):
                return f"Error: todo[{i}].status must be pending/in_progress/completed"

        # Write to file in workspace
        todo_path = _todo_store_path(ctx.cwd)
        todo_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            todo_path.write_text(
                json.dumps(todos, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            return f"Error: cannot write todo file: {exc}"

        # Return summary
        pending = sum(1 for t in todos if t["status"] == "pending")
        in_progress = sum(1 for t in todos if t["status"] == "in_progress")
        completed = sum(1 for t in todos if t["status"] == "completed")

        return f"Updated: {completed} done, {in_progress} in progress, {pending} pending ({len(todos)} total)"


class TodoReadTool:
    """Read the current task list."""

    name: ClassVar[str] = "todo_read"
    description: ClassVar[str] = (
        "Read the current task list to check progress."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        todo_path = _todo_store_path(ctx.cwd)

        if not todo_path.is_file():
            return "No task list exists yet."

        try:
            content = todo_path.read_text(encoding="utf-8")
            todos = json.loads(content)
        except (OSError, json.JSONDecodeError) as exc:
            return f"Error reading todo file: {exc}"

        if not todos:
            return "Task list is empty."

        lines: list[str] = []
        for i, todo in enumerate(todos, 1):
            status = todo.get("status", "pending")
            marker = {"pending": "○", "in_progress": "◑", "completed": "●"}[status]
            lines.append(f"{marker} {i}. {todo['content']}")

        return "\n".join(lines)


def _todo_store_path(cwd: Path) -> Path:
    """Path to the todo JSON file in the workspace."""
    return cwd / ".berry" / "todos.json"
