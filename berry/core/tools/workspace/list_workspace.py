"""ListWorkspaceTool — list materials for a milestone.

Pure DB read (no fs touch needed). Returns a JSON list with metadata the
LLM can feed back into ``read_md`` / ``edit_md`` calls (material_id,
filename, source_url, summary, size_bytes).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from uuid import UUID

from berry.assistants.learning.repos.material_repo import MaterialRepo
from berry.core.tools.base import ToolContext


class ListWorkspaceTool:
    name: ClassVar[str] = "list_workspace"
    description: ClassVar[str] = (
        "List all material files saved under a milestone. Returns each "
        "material's id, filename, source_url, summary, and size_bytes — use "
        "this before read_md to discover what's already been saved, or "
        "before write_md to avoid duplicate filenames."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "milestone_id": {
                "type": "string",
                "description": "UUID of the milestone whose materials to list.",
            },
        },
        "required": ["milestone_id"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.db is None:
            raise RuntimeError("list_workspace requires a db session in ToolContext")

        milestone_id = UUID(str(args["milestone_id"]))
        materials = await MaterialRepo(ctx.db).list_by_milestone(milestone_id)
        return json.dumps(
            [
                {
                    "material_id": str(m.id),
                    "filename": m.filename,
                    "source_url": m.source_url,
                    "summary": m.summary,
                    "size_bytes": m.size_bytes,
                }
                for m in materials
            ],
            ensure_ascii=False,
        )
