"""MemoryReadTool — read the current memory list."""

from __future__ import annotations

from typing import Any, ClassVar

from berry.core.tools.base import ToolContext
from berry.core.tools.memory.store import MemoryStore


class MemoryReadTool:
    """Read the current memory list to check what is remembered."""

    name: ClassVar[str] = "memory_read"
    description: ClassVar[str] = (
        "Read the current memory list to check what is remembered. "
        "Use this to recall user preferences, project facts, or past feedback."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        memory_dir = ctx.data_root / "memory" / str(ctx.user_id)
        memory_dir.mkdir(parents=True, exist_ok=True)
        store = MemoryStore(memory_dir)
        entries = store.list_all()

        if not entries:
            return "No memories stored yet."

        lines: list[str] = []
        for entry in entries:
            marker = {
                "user": "[user]",
                "feedback": "[feedback]",
                "project": "[project]",
                "reference": "[reference]",
            }.get(entry.type, "[?]")

            body_preview = entry.body.split("\n")[0][:120]
            lines.append(f"{marker} {entry.name}: {entry.description}")
            if body_preview:
                lines.append(f"    {body_preview}")

        return "\n".join(lines)
