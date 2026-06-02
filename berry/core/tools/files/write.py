"""WriteFileTool — LLM-callable wrapper around :func:`ops.write_file_in_workspace`.

Schema matches claw-code's ``write_file`` (lib.rs:434-447). Always goes through
ApprovalChannel because it can overwrite — see WhitelistPolicy registration in
``berry/entrypoints/cli.py``.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext
from berry.core.tools.files.ops import write_file_in_workspace


class WriteFileTool:
    name: ClassVar[str] = "write_file"
    description: ClassVar[str] = "Write a text file in the workspace."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        result = write_file_in_workspace(
            path=str(args["path"]),
            content=str(args["content"]),
            workspace=ctx.cwd,
        )
        return json.dumps(result, ensure_ascii=False)
