"""EditMdTool — replace a unique substring inside a material file.

Same edit-by-substring contract as Anthropic's Edit tool (claude-code):
``old_string`` must appear EXACTLY ONCE. If it appears zero times → "not
found". If it appears multiple times → "ambiguous, give more context".
This forces the LLM to write surgical, unambiguous edits instead of
broad search-and-replace that could clobber the wrong section.

Sequence (mirroring write_md's commit pattern):
1. Resolve material → milestone → goal → path. (DB-driven, LLM can't
   fake the path.)
2. Read current content from disk.
3. Validate ``old_string`` uniqueness.
4. Write new content (keeping the old content as a Python-side backup).
5. Update DB metadata (size_bytes, content_hash). On failure, restore
   the file from the in-memory backup and re-raise.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from typing import Any, ClassVar
from uuid import UUID

from berry.assistants.learning.repos.material_repo import MaterialRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.workspace.paths import resolve_material_path
from berry.core.tools.base import ToolContext


class EditMdTool:
    name: ClassVar[str] = "edit_md"
    description: ClassVar[str] = (
        "Edit an existing material file by replacing a unique substring. "
        "The old_string must match exactly once in the file — include enough "
        "surrounding context if a short fragment would be ambiguous. Returns "
        "JSON describing what changed."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "material_id": {
                "type": "string",
                "description": "UUID of the material to edit.",
            },
            "old_string": {
                "type": "string",
                "description": (
                    "The exact substring to find. Must occur exactly once "
                    "in the file."
                ),
            },
            "new_string": {
                "type": "string",
                "description": "The replacement substring.",
            },
        },
        "required": ["material_id", "old_string", "new_string"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.db is None:
            raise RuntimeError("edit_md requires a db session in ToolContext")

        material_id = UUID(str(args["material_id"]))
        old_string = str(args["old_string"])
        new_string = str(args["new_string"])
        if not old_string:
            raise ValueError("edit_md old_string must be non-empty")

        material_repo = MaterialRepo(ctx.db)
        material = await material_repo.get_by_id(material_id)
        if material is None:
            raise FileNotFoundError(f"material {material_id} not found")

        milestone = await MilestoneRepo(ctx.db).get_by_id(material.milestone_id)
        if milestone is None:
            raise FileNotFoundError(
                f"orphan material {material_id}: milestone gone"
            )

        path = resolve_material_path(
            ctx.data_root, milestone.goal_id, milestone.id, material.filename
        )
        if not path.exists():
            raise FileNotFoundError(
                f"material {material_id} row exists but file missing: {path}"
            )

        # 2. Read.
        original_content = path.read_text(encoding="utf-8")

        # 3. Uniqueness check on old_string.
        occurrences = original_content.count(old_string)
        if occurrences == 0:
            raise ValueError(
                f"old_string not found in {material.filename!r}; "
                "include exact characters from the file"
            )
        if occurrences > 1:
            raise ValueError(
                f"old_string appears {occurrences} times in {material.filename!r}; "
                "include more surrounding context so the match is unique"
            )

        new_content = original_content.replace(old_string, new_string, 1)

        # 4. Write file (in-memory backup of the original keeps rollback simple).
        path.write_text(new_content, encoding="utf-8")

        # 5. Update DB metadata; on failure, restore the file.
        try:
            new_bytes = new_content.encode("utf-8")
            await material_repo.update_after_edit(
                material_id=material.id,
                size_bytes=len(new_bytes),
                content_hash=hashlib.sha256(new_bytes).hexdigest(),
            )
        except Exception:
            # Best-effort restore; if it fails, the original DB error wins.
            with contextlib.suppress(OSError):
                path.write_text(original_content, encoding="utf-8")
            raise

        return json.dumps(
            {
                "material_id": str(material.id),
                "filename": material.filename,
                "old_size": len(original_content.encode("utf-8")),
                "new_size": len(new_content.encode("utf-8")),
            },
            ensure_ascii=False,
        )
