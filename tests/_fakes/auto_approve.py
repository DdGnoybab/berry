"""Test-only ApprovalChannel implementations.

Lives under ``tests/_fakes/`` (NOT under ``berry/``) to make it physically
impossible for production entrypoints to import these. Approving every tool
call without prompting the user would be a security regression in any real
channel; isolating the fakes here is a structural defense.
"""

from __future__ import annotations

from typing import Any

from berry.core.tools.base import ToolContext


class AutoApproveChannel:
    """``ask`` always returns True. Used to test the happy path of
    ConversationRuntime when the runtime is configured to require approval
    for some tool. Do NOT use in production.
    """

    async def ask(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
        reason: str | None = None,
    ) -> bool:
        return True


class AutoDenyChannel:
    """``ask`` always returns False. Used to test the user-denied path
    (runtime turns False into ``ToolResultBlock(is_error=True, output="user denied")``
    fed back to the LLM). Do NOT use in production.
    """

    async def ask(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
        reason: str | None = None,
    ) -> bool:
        return False
