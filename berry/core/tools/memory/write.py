"""MemoryWriteTool — save persistent knowledge to memory."""

from __future__ import annotations

from typing import Any, ClassVar

from berry.core.tools.base import ToolContext
from berry.core.tools.memory.store import MemoryStore


class MemoryWriteTool:
    """Save a user preference, constraint, or project fact to persistent memory."""

    name: ClassVar[str] = "memory_write"
    description: ClassVar[str] = (
        "Save a user preference, constraint, or project fact to persistent memory. "
        "Memories survive across sessions and compaction. "
        "Use this when the user expresses a stable preference, constraint, or fact."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Short slug name for the memory (e.g. 'user-prefer-tabs').",
            },
            "type": {
                "type": "string",
                "enum": ["user", "feedback", "project", "reference"],
                "description": (
                    "user: user preference/identity. "
                    "feedback: how to do things. "
                    "project: project background. "
                    "reference: where things are."
                ),
            },
            "description": {
                "type": "string",
                "description": "One-line description shown in the memory index.",
            },
            "body": {
                "type": "string",
                "description": "Full memory content — details, reasoning, how to apply.",
            },
        },
        "required": ["name", "type", "description", "body"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        name = args.get("name", "").strip()
        mem_type = args.get("type", "").strip()
        description = args.get("description", "").strip()
        body = args.get("body", "").strip()

        if not name:
            return "Error: name must not be empty"
        if not mem_type:
            return "Error: type must not be empty"
        if not body:
            return "Error: body must not be empty"

        memory_dir = ctx.data_root / "memory" / str(ctx.user_id)
        memory_dir.mkdir(parents=True, exist_ok=True)
        store = MemoryStore(memory_dir)
        filepath = store.write(name, mem_type, description, body)
        return f"Memory '{name}' saved to {filepath.name}."
