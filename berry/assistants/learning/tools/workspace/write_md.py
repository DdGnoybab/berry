"""WriteMdTool — write a new .md to the milestone workspace.

Sequence (per spec §七.workspace + Q6 decision):
1. Verify ``goal_id`` and ``milestone_id`` exist and the milestone really
   belongs to that goal — LLM-supplied UUIDs are not trusted.
2. Resolve the canonical filesystem path via ``resolve_material_path``,
   which enforces the data_root scope and filename whitelist.
3. Pre-check uniqueness (``MaterialRepo.get_by_milestone_filename``) — if
   a row already exists, refuse and tell the LLM to use ``edit_md`` instead.
4. Write the file to disk.
5. Insert the metadata row in ``materials``. If insert fails, delete the
   just-written file (orphan cleanup). Re-raise the original error.

Returns JSON with ``material_id`` and the workspace-relative ``path`` so
the LLM can reference it in subsequent ``read_md`` / ``edit_md`` calls.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from typing import Any, ClassVar
from uuid import UUID

from berry.assistants.learning.repos.material_repo import MaterialRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.workspace.paths import (
    WorkspacePathError,
    resolve_material_path,
)
from berry.core.tools.base import ToolContext


class WriteMdTool:
    name: ClassVar[str] = "write_md"
    description: ClassVar[str] = (
        "Create a NEW markdown file inside a milestone's workspace. Use this "
        "after web_fetch when you've gathered learning content and want to "
        "save it as a study material. The file is stored under "
        "data/goals/<goal_id>/milestones/<milestone_id>/<filename>. "
        "If a file with the same name already exists in this milestone, "
        "this tool will refuse — use edit_md to modify existing files."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "goal_id": {
                "type": "string",
                "description": "UUID of the goal this material belongs to.",
            },
            "milestone_id": {
                "type": "string",
                "description": "UUID of the milestone (must belong to the goal).",
            },
            "filename": {
                "type": "string",
                "description": (
                    "ASCII-only filename ending in .md "
                    "(e.g. '01-intro.md', 'lesson_2.md')."
                ),
            },
            "content": {
                "type": "string",
                "description": "The full markdown content of the file.",
            },
            "source_url": {
                "type": "string",
                "description": "Optional URL the content was sourced from.",
            },
            "source_title": {
                "type": "string",
                "description": "Optional human-readable title of the source.",
            },
            "summary": {
                "type": "string",
                "description": (
                    "Optional ~150-char summary used by list_workspace and "
                    "feishu cards. If omitted, list_workspace shows nothing."
                ),
            },
        },
        "required": ["goal_id", "milestone_id", "filename", "content"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.db is None:
            raise RuntimeError("write_md requires a db session in ToolContext")

        goal_id = UUID(str(args["goal_id"]))
        milestone_id = UUID(str(args["milestone_id"]))
        filename = str(args["filename"])
        content = str(args["content"])

        # 1. Validate milestone exists + belongs to claimed goal.
        milestone = await MilestoneRepo(ctx.db).get_by_id(milestone_id)
        if milestone is None:
            raise WorkspacePathError(f"milestone {milestone_id} not found")
        if milestone.goal_id != goal_id:
            raise WorkspacePathError(
                f"milestone {milestone_id} does not belong to goal {goal_id}"
            )

        # 2. Resolve and validate path scope.
        path = resolve_material_path(ctx.data_root, goal_id, milestone_id, filename)

        # 3. Uniqueness pre-check.
        material_repo = MaterialRepo(ctx.db)
        existing = await material_repo.get_by_milestone_filename(milestone_id, filename)
        if existing is not None:
            raise FileExistsError(
                f"{filename!r} already exists in this milestone "
                f"(material_id={existing.id}). Use edit_md to modify."
            )

        # 4. Write file.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        # 5. Insert DB row; on failure, delete the file (orphan cleanup).
        try:
            content_bytes = content.encode("utf-8")
            material = await material_repo.insert(
                milestone_id=milestone_id,
                filename=filename,
                size_bytes=len(content_bytes),
                content_hash=hashlib.sha256(content_bytes).hexdigest(),
                source_url=args.get("source_url"),
                source_title=args.get("source_title"),
                summary=args.get("summary"),
            )
        except Exception:
            # Cleanup is best-effort; if it fails, the original error wins.
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
            raise

        return json.dumps(
            {
                "material_id": str(material.id),
                "path": str(path.relative_to(ctx.data_root.resolve())),
                "size_bytes": material.size_bytes,
            },
            ensure_ascii=False,
        )
