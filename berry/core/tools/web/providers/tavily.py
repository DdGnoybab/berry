"""TavilyProvider — wraps tavily-python AsyncTavilyClient.search.

Tavily is an LLM-oriented search API: results come pre-cleaned (snippet
text instead of raw HTML), free tier 1k req/month. Day-1 default.
"""

from __future__ import annotations

from typing import ClassVar

from tavily import AsyncTavilyClient

from berry.core.tools.web.base import SearchResult


class TavilyProvider:
    """Adapter from Tavily's API shape to berry's ``SearchResult``."""

    name: ClassVar[str] = "tavily"

    def __init__(self, api_key: str, timeout_s: float = 15.0) -> None:
        self._client = AsyncTavilyClient(api_key=api_key)
        self._timeout_s = timeout_s

    async def search(self, query: str, n: int = 5) -> list[SearchResult]:
        # Tavily returns {"results": [{"title", "url", "content", ...}, ...]}.
        # Their "content" is the snippet — what berry calls "snippet".
        raw = await self._client.search(
            query=query,
            max_results=n,
            search_depth="basic",
            timeout=self._timeout_s,
        )
        items = raw.get("results", [])
        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
            for item in items
        ]
