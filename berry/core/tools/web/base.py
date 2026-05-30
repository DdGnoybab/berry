"""SearchProvider Protocol + SearchResult model.

Day-1: only ``TavilyProvider`` exists. Future providers (union-search-skill,
self-hosted SearXNG) just implement this same Protocol — the WebSearchTool
asks the registry for a provider by name and doesn't care about the
implementation details.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel


class SearchResult(BaseModel):
    """One search hit. The minimum we need to render to the LLM and to let
    it decide whether to follow up with web_fetch.
    """

    title: str
    url: str
    snippet: str


@runtime_checkable
class SearchProvider(Protocol):
    """Async search provider — given a query, returns at most ``n`` results.

    Implementations decide their own fetch / parse / API-call strategy. The
    runtime only sees this interface.
    """

    name: ClassVar[str]

    async def search(self, query: str, n: int = 5) -> list[SearchResult]: ...
