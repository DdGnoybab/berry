"""CLI implementation of ApprovalChannel.

Prints a single-line ``[approval] tool(args) 允许?[y/N]`` and reads stdin.
``y`` / ``yes`` (case-insensitive) approves; anything else (incl. EOF) denies.

Why ``asyncio.to_thread``: ``input()`` is blocking. Running it inside the
event loop would freeze every other coroutine until the user types. Offloading
to a thread keeps the loop responsive (matters once we add timeouts in V1+).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from berry.core.tools.base import ToolContext


class CliApprovalChannel:
    """Prompts the user via stdin. ``ask`` returns True iff the user typed y/yes."""

    async def ask(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
        reason: str | None = None,
    ) -> bool:
        reason_part = f" — {reason}" if reason else ""
        prompt = f"[approval]{reason_part} {tool_name}({_compact(args)}) 允许?[y/N] "
        try:
            answer = await asyncio.to_thread(input, prompt)
        except EOFError:
            # Pipe closed / Ctrl-D — treat as denial, do not crash the turn.
            return False
        return answer.strip().lower() in {"y", "yes"}


def _compact(value: dict[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)
