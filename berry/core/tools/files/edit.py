"""EditFileTool — LLM-callable wrapper around :func:`ops.edit_file_in_workspace`.

Schema matches claw-code's ``edit_file`` (lib.rs:448-462). Multi-match without
``replace_all`` is rejected here, diverging from claw-code; see spec § 11 ADR.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext
from berry.core.tools.files.ops import edit_file_in_workspace


class EditFileTool:
    name: ClassVar[str] = "edit_file"
    description: ClassVar[str] = "Replace text in a workspace file."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        result = edit_file_in_workspace(
            path=str(args["path"]),
            old_string=str(args["old_string"]),
            new_string=str(args["new_string"]),
            replace_all=bool(args.get("replace_all", False)),
            workspace=ctx.cwd,
        )
        return json.dumps(result, ensure_ascii=False)
