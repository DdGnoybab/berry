"""Test-only Tavily client stand-in.

Replaces ``AsyncTavilyClient.search`` with a canned response so tests don't
depend on network or the real Tavily key. Used by monkeypatching
``berry.core.tools.web.providers.tavily.AsyncTavilyClient``.
"""

from __future__ import annotations

from typing import Any


class FakeAsyncTavilyClient:
    """Records calls and returns scripted responses."""

    def __init__(self, *, api_key: str, results: list[dict[str, Any]] | None = None) -> None:
        self.api_key = api_key
        self.calls: list[dict[str, Any]] = []
        self._results = results if results is not None else _DEFAULT_RESULTS

    async def search(
        self,
        *,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        timeout: float = 60,
        **_: Any,
    ) -> dict[str, Any]:
        self.calls.append({
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "timeout": timeout,
        })
        return {
            "query": query,
            "results": self._results[:max_results],
        }


_DEFAULT_RESULTS: list[dict[str, Any]] = [
    {
        "title": "LangGraph official tutorial",
        "url": "https://langchain-ai.github.io/langgraph/tutorials/",
        "content": "Step-by-step tutorial covering StateGraph fundamentals.",
    },
    {
        "title": "Conditional edges in LangGraph",
        "url": "https://example.com/conditional-edges",
        "content": "How to route between nodes based on state.",
    },
    {
        "title": "Checkpointer overview",
        "url": "https://example.com/checkpointer",
        "content": "Persistence and resume in LangGraph.",
    },
]
