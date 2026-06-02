"""ReadFileTool — LLM-callable wrapper around :func:`ops.read_file_in_workspace`.

Schema and description match claw-code's ``read_file`` tool spec
(reference/claw-code_1/rust/crates/tools/src/lib.rs:418-433) byte-for-byte
so anything that already understands claw-code's tool catalog can call this
without translation.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext
from berry.core.tools.files.ops import read_file_in_workspace


class ReadFileTool:
    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = "Read a text file from the workspace."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "minimum": 0},
            "limit": {"type": "integer", "minimum": 1},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        result = read_file_in_workspace(
            path=str(args["path"]),
            offset=args.get("offset"),
            limit=args.get("limit"),
            workspace=ctx.cwd,
        )
        return json.dumps(result, ensure_ascii=False)
