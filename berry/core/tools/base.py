"""Tool Protocol + ToolContext.

Tools are leaf nodes in berry's agent dependency graph (CLAUDE.md §架构 rule 9):
they don't import core.agent. Instead, ConversationRuntime constructs a
ToolContext per turn and passes it to each Tool.execute call.

The Protocol is runtime-checkable so isinstance(x, Tool) works in tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession


class ToolContext(BaseModel):
    """Per-turn execution context shared by ApprovalPolicy + every Tool.execute call.

    Constructed by ConversationRuntime at the start of each turn (Round 2).
    Tools are not allowed to mutate this — treat as read-only.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    session_id: UUID
    user_id: UUID
    goal_id: UUID | None = None      # learning domain only
    db: AsyncSession | None    # shared for the turn; pass None explicitly in tests
    data_root: Path                  # = settings.data_root, used by workspace tools


@runtime_checkable
class Tool(Protocol):
    """A tool the LLM can call.

    Implementations must:
    - declare a unique `name` (used by LLM tool_use blocks)
    - provide a `description` (LLM uses this to decide when to call)
    - provide a JSON Schema `input_schema` (LLM uses this to construct args)
    - implement `execute(args, ctx) -> str` returning the ToolResultBlock.output text
    """

    name: str
    description: str
    input_schema: dict[str, Any]

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str: ...
