"""WebSearchTool — LLM-callable wrapper around SearchProviderRegistry.

The LLM's input schema mirrors what the Anthropic / OpenAI tool-call
contract sees: a string query, optional integer ``n``. The tool resolves the
default provider (set in search.yaml) and returns JSON the model can read.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext
from berry.core.tools.web.registry import SearchProviderRegistry


class WebSearchTool:
    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = (
        "Search the public web. Returns up to `n` (default 5) results with "
        "title, URL, and snippet. Use this to find authoritative sources, "
        "recent docs, or examples before answering questions about specific "
        "libraries, APIs, or current events."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "n": {
                "type": "integer",
                "description": "Maximum number of results (1-10). Default 5.",
                "minimum": 1,
                "maximum": 10,
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(self, registry: SearchProviderRegistry) -> None:
        self._registry = registry

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        query = str(args["query"])
        n = int(args.get("n", 5))
        n = max(1, min(n, 10))

        provider = self._registry.default()
        results = await provider.search(query, n=n)
        return json.dumps(
            [r.model_dump() for r in results],
            ensure_ascii=False,
        )
