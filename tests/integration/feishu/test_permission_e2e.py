"""End-to-end: LayeredPolicy + ApprovalChannel pass through ConversationRuntime.

Drives ``ConversationRuntime._handle_one_tool_use`` directly with a
``ToolUseBlock`` so we don't need an LLM, but we exercise the full
policy → channel → tool-execution path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from berry.core.agent.approval import ApprovalChannel
from berry.core.agent.runtime import ConversationRuntime
from berry.core.agent.tool_registry import ToolRegistry
from berry.core.llm.types import ToolUseBlock
from berry.core.tools.base import ToolContext
from berry.security.permissions import LayeredPolicy
from tests._fakes.auto_approve import AutoApproveChannel, AutoDenyChannel


class _Echo:
    """Minimal Tool implementation: echoes args back."""

    name = "bash"
    description = "fake bash"
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"ran {args.get('command')}"


def _runtime(channel: ApprovalChannel) -> ConversationRuntime:
    return ConversationRuntime(
        llm_gateway=None,        # type: ignore[arg-type]   (not used in this test)
        tool_registry=ToolRegistry([_Echo()]),
        approval_policy=LayeredPolicy(),
        approval_channel=channel,
        db_session_factory=None,  # type: ignore[arg-type]  (not used)
        model_id="main",
    )


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp"),
        cwd=Path("/tmp"),
    )


@pytest.mark.asyncio
async def test_deny_list_yields_auto_denied_tool_result() -> None:
    rt = _runtime(AutoApproveChannel())
    block = await rt._handle_one_tool_use(   # type: ignore[attr-defined]
        ToolUseBlock(id="t1", name="bash", input={"command": "rm -rf /"}),
        _ctx(),
    )
    assert block.is_error is True
    assert "auto-denied" in block.output
    assert "rm -rf /" in block.output


@pytest.mark.asyncio
async def test_rule_match_with_auto_approve_executes() -> None:
    rt = _runtime(AutoApproveChannel())
    block = await rt._handle_one_tool_use(   # type: ignore[attr-defined]
        ToolUseBlock(id="t1", name="bash", input={"command": "rm foo.py"}),
        _ctx(),
    )
    assert block.is_error is False
    assert "ran rm foo.py" in block.output


@pytest.mark.asyncio
async def test_rule_match_with_auto_deny_yields_user_denied() -> None:
    rt = _runtime(AutoDenyChannel())
    block = await rt._handle_one_tool_use(   # type: ignore[attr-defined]
        ToolUseBlock(id="t1", name="bash", input={"command": "rm foo.py"}),
        _ctx(),
    )
    assert block.is_error is True
    assert "user denied" in block.output


@pytest.mark.asyncio
async def test_safe_command_skips_approval() -> None:
    rt = _runtime(AutoDenyChannel())   # would deny if asked, but won't be asked
    block = await rt._handle_one_tool_use(   # type: ignore[attr-defined]
        ToolUseBlock(id="t1", name="bash", input={"command": "ls -la"}),
        _ctx(),
    )
    assert block.is_error is False
    assert "ran ls -la" in block.output
