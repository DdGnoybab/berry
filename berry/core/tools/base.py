"""Tool Protocol + ToolContext.

Tools are leaf nodes in berry's agent dependency graph (CLAUDE.md §架构 rule 9):
they don't import core.agent. Instead, ConversationRuntime constructs a
ToolContext per turn and passes it to each Tool.execute call.

The Protocol is runtime-checkable so isinstance(x, Tool) works in tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession


class ToolContext(BaseModel):
    """Per-turn execution context shared by ApprovalPolicy + every Tool.execute call.

    Constructed by ConversationRuntime at the start of each turn (Round 2).
    Tools are not allowed to mutate this — treat as read-only.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    session_id: str
    user_id: UUID
    goal_id: UUID | None = None      # learning domain only
    db: AsyncSession | None    # shared for the turn; pass None explicitly in tests
    data_root: Path                  # = settings.data_root, used by berry-internal data
    cwd: Path                        # LLM workspace root; file tools enforce stay-within-cwd


@runtime_checkable
class Tool(Protocol):
    """A tool the LLM can call.

    Implementations must:
    - declare a unique `name` (used by LLM tool_use blocks)
    - provide a `description` (LLM uses this to decide when to call)
    - provide a JSON Schema `input_schema` (LLM uses this to construct args)
    - implement `execute(args, ctx) -> str` returning the ToolResultBlock.output text

    name / description / input_schema are class-level constants for every tool
    we know about — so they are declared as ``ClassVar`` here. Implementers may
    set them either as bare class attributes (Python erases the type at runtime)
    or with explicit ``ClassVar`` annotations; both satisfy the Protocol.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[dict[str, Any]]

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str: ...
