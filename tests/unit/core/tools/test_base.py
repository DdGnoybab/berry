"""Tests for Tool Protocol + ToolContext."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

import pytest
from pydantic import ValidationError

from berry.core.tools.base import Tool, ToolContext


class FakeTool:
    """Minimal Tool implementation for Protocol conformance testing."""

    name: ClassVar[str] = "fake_tool"
    description: ClassVar[str] = "A fake tool for tests."
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}, "required": []}

    async def execute(self, args: dict, ctx: ToolContext) -> str:
        return "ok"


def test_fake_tool_satisfies_tool_protocol() -> None:
    """A class with name/description/input_schema/execute should satisfy Protocol."""
    assert isinstance(FakeTool(), Tool)


def test_tool_context_requires_session_and_user() -> None:
    """ToolContext must have session_id and user_id."""
    ctx = ToolContext(
        session_id=uuid4(),
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp/berry_test"),
    )
    assert ctx.goal_id is None
    assert ctx.data_root == Path("/tmp/berry_test")


def test_tool_context_rejects_missing_session_id() -> None:
    """Pydantic should reject ToolContext without session_id."""
    with pytest.raises(ValidationError):
        ToolContext(  # type: ignore[call-arg]
            user_id=uuid4(),
            db=None,
            data_root=Path("/tmp/berry_test"),
        )
