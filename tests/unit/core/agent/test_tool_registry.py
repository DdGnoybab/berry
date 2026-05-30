"""Tests for ToolRegistry."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from berry.core.agent.tool_registry import ToolRegistry
from berry.core.llm.types import LlmTool
from berry.core.tools.base import Tool, ToolContext


def _make_tool(name: str = "echo", desc: str = "echoes input") -> Tool:
    class _T:
        def __init__(self) -> None:
            self.name = name
            self.description = desc
            self.input_schema = {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            }

        async def execute(self, args: dict, ctx: ToolContext) -> str:
            return str(args.get("text", ""))

    return _T()  # type: ignore[return-value]


def test_registry_get_returns_registered_tool() -> None:
    t = _make_tool("echo")
    reg = ToolRegistry([t])
    assert reg.get("echo") is t


def test_registry_get_raises_for_unknown() -> None:
    reg = ToolRegistry([_make_tool("a")])
    with pytest.raises(KeyError, match="tool not registered"):
        reg.get("does_not_exist")


def test_registry_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="duplicate tool name"):
        ToolRegistry([_make_tool("dup"), _make_tool("dup")])


def test_registry_schemas_returns_llm_tools() -> None:
    t = _make_tool("echo", "echoes input")
    reg = ToolRegistry([t])
    schemas = reg.schemas()
    assert len(schemas) == 1
    assert isinstance(schemas[0], LlmTool)
    assert schemas[0].name == "echo"
    assert schemas[0].description == "echoes input"
    assert schemas[0].input_schema["properties"]["text"]["type"] == "string"


def test_registry_empty_list_is_allowed() -> None:
    reg = ToolRegistry([])
    assert reg.schemas() == []


@pytest.mark.asyncio
async def test_registry_get_then_execute_roundtrip() -> None:
    """Sanity: a registry-fetched tool actually executes."""
    reg = ToolRegistry([_make_tool("echo")])
    tool = reg.get("echo")
    ctx = ToolContext(
        session_id=uuid4(),
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp/berry_test"),
    )
    result = await tool.execute({"text": "hi"}, ctx)
    assert result == "hi"
