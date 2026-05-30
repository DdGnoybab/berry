"""ReadMdTool — read an existing material's content back into the LLM context.

Path is resolved from DB (material_id → milestone → goal → filename) so the
LLM cannot supply an arbitrary path. The path-scope guard still runs as a
defense in depth.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from uuid import UUID

from berry.assistants.learning.repos.material_repo import MaterialRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.core.tools.base import ToolContext
from berry.core.tools.workspace.paths import resolve_material_path

# Cap how many chars of a single .md we feed to the LLM in one shot.
# 30k matches web_fetch's truncation budget — keeps a single read from
# blowing past one Anthropic prompt.
_MAX_CHARS = 30_000


class ReadMdTool:
    name: ClassVar[str] = "read_md"
    description: ClassVar[str] = (
        "Read the contents of a material file by material_id. Returns the "
        "filename, full content, and source_url if it has one. Use this when "
        "you need to re-consult content you previously wrote — e.g. before "
        "answering a question that should reference earlier material."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "material_id": {
                "type": "string",
                "description": "UUID of the material to read.",
            },
        },
        "required": ["material_id"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.db is None:
            raise RuntimeError("read_md requires a db session in ToolContext")

        material_id = UUID(str(args["material_id"]))
        material_repo = MaterialRepo(ctx.db)
        material = await material_repo.get_by_id(material_id)
        if material is None:
            raise FileNotFoundError(f"material {material_id} not found")

        milestone = await MilestoneRepo(ctx.db).get_by_id(material.milestone_id)
        if milestone is None:
            # Should be unreachable thanks to FK CASCADE, but defend anyway.
            raise FileNotFoundError(
                f"orphan material {material_id}: milestone {material.milestone_id} gone"
            )

        path = resolve_material_path(
            ctx.data_root, milestone.goal_id, milestone.id, material.filename
        )
        if not path.exists():
            raise FileNotFoundError(
                f"material {material_id} row exists but file missing: {path}"
            )

        content = path.read_text(encoding="utf-8")
        truncated = False
        if len(content) > _MAX_CHARS:
            content = content[:_MAX_CHARS] + "\n\n[truncated]"
            truncated = True

        return json.dumps(
            {
                "material_id": str(material.id),
                "filename": material.filename,
                "source_url": material.source_url,
                "content": content,
                "truncated": truncated,
            },
            ensure_ascii=False,
        )
