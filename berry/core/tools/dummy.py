"""Dummy tools for end-to-end testing of the turn loop.

These exist so Round 2 has something the LLM can call without depending on
Round 3 (web tools) or Round 4 (learning tools). Two tools cover the two
paths through the runtime:

- ``echo_tool`` — succeeds. Verifies the happy path: LLM → tool_use → result → LLM.
- ``fail_tool`` — always raises. Verifies the error path: tool exception is
  caught by the runtime and turned into ``is_error=True`` ToolResultBlock,
  so the LLM sees a graceful "failure" message and can adapt.

These tools are NOT part of the production assistant tool sets. Round 4 will
load real learning tools instead. The file stays in the repo as debug fodder.

TODO (Round 4 cleanup): once real tools land, remove the import in
``berry/entrypoints/cli.py`` (the file itself can stay).
"""

from __future__ import annotations

from typing import Any, ClassVar

from berry.core.tools.base import ToolContext


class EchoTool:
    """Returns whatever ``text`` the LLM passes in. The simplest possible
    successful tool — used to verify the runtime can complete a tool_use ↔
    tool_result round trip.
    """

    name: ClassVar[str] = "echo_tool"
    description: ClassVar[str] = (
        "Echo the provided text back unchanged. Use this when the user "
        "explicitly asks you to test or echo a string."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to echo back.",
            }
        },
        "required": ["text"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return str(args["text"])


class FailTool:
    """Raises on every call. Used to verify the runtime converts tool
    exceptions into ``is_error=True`` ToolResultBlocks instead of crashing
    the turn.
    """

    name: ClassVar[str] = "fail_tool"
    description: ClassVar[str] = (
        "Always fails with an exception. Use this only when explicitly asked "
        "to test the error-handling path."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        raise RuntimeError("fail_tool intentionally failed (dummy tool)")
