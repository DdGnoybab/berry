"""BashTool — execute shell commands in the workspace.

Mirrors claw-code's bash tool. Runs a command via subprocess, returns
stdout + stderr. Enforces timeout and cwd restriction.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext


class BashTool:
    """Execute a shell command in the workspace."""

    name: ClassVar[str] = "bash"
    description: ClassVar[str] = (
        "Execute a shell command in the current workspace. "
        "Returns stdout and stderr. Use for running scripts, "
        "checking system state, installing packages, etc."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "minimum": 1,
                "description": "Timeout in seconds. Default 120.",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        command = args["command"]
        timeout = args.get("timeout", 120)

        if not command.strip():
            return "Error: command must not be empty"

        try:
            result = await asyncio.wait_for(
                _run_command(command, cwd=ctx.cwd, timeout=timeout),
                timeout=timeout + 5,
            )
        except asyncio.TimeoutError:
            return f"Error: command timed out after {timeout}s"

        return result


async def _run_command(command: str, cwd: Any, timeout: int) -> str:
    """Run command in subprocess, return formatted output."""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"Error: command timed out after {timeout}s"

    parts: list[str] = []

    stdout_text = stdout.decode("utf-8", errors="replace").rstrip()
    stderr_text = stderr.decode("utf-8", errors="replace").rstrip()

    if stdout_text:
        parts.append(stdout_text)
    if stderr_text:
        parts.append(f"[stderr]\n{stderr_text}")

    exit_code = proc.returncode
    if exit_code != 0:
        parts.append(f"[exit code: {exit_code}]")

    if not parts:
        return "(no output)"

    return "\n".join(parts)
