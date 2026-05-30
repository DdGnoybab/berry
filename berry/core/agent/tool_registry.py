"""ToolRegistry — name-to-Tool lookup + LLM schema export.

Lives under core/agent/ rather than core/tools/ because:
- registry is consumed by ConversationRuntime (core/agent),
- import-linter rule "core.tools does not depend on core.agent" forbids
  putting registry-of-tools in core/tools without circular pain.
"""

from __future__ import annotations

from berry.core.llm.types import LlmTool
from berry.core.tools.base import Tool


class ToolRegistry:
    """Holds a fixed set of Tools for the lifetime of one ConversationRuntime instance.

    Construction is the only mutation point: add tools at instantiation,
    runtime never adds or removes after.
    """

    def __init__(self, tools: list[Tool]) -> None:
        self._validate_no_duplicates(tools)
        # dict preserves insertion order (Python 3.7+); schemas() relies on this
        # to return tools in registration order
        self._by_name: dict[str, Tool] = {t.name: t for t in tools}

    @staticmethod
    def _validate_no_duplicates(tools: list[Tool]) -> None:
        seen: set[str] = set()
        for t in tools:
            if t.name in seen:
                raise ValueError(f"duplicate tool name: {t.name!r}")
            seen.add(t.name)

    def get(self, name: str) -> Tool:
        """Look up by name; raises KeyError if missing."""
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(f"tool not registered: {name!r}") from exc

    def schemas(self) -> list[LlmTool]:
        """Return LLM-side schemas for every registered tool, in registration order."""
        return [
            LlmTool(
                name=t.name,
                description=t.description,
                input_schema=t.input_schema,
            )
            for t in self._by_name.values()
        ]
