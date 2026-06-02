"""Unit tests for WebSearchTool — uses a hand-rolled fake SearchProvider so
no Tavily SDK / network is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

import pytest

from berry.core.tools.base import ToolContext
from berry.core.tools.web.base import SearchResult
from berry.core.tools.web.search import WebSearchTool


class _StubProvider:
    name: ClassVar[str] = "stub"

    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results
        self.last_call: tuple[str, int] | None = None

    async def search(self, query: str, n: int = 5) -> list[SearchResult]:
        self.last_call = (query, n)
        return self._results[:n]


class _StubRegistry:
    def __init__(self, provider: _StubProvider) -> None:
        self._provider = provider

    def default(self) -> _StubProvider:
        return self._provider


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="test-session-id",
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp/berry_test"),
        cwd=Path("/tmp/berry_test"),
    )


@pytest.mark.asyncio
async def test_search_returns_json_list_of_results() -> None:
    provider = _StubProvider([
        SearchResult(title="A", url="https://a", snippet="snip A"),
        SearchResult(title="B", url="https://b", snippet="snip B"),
    ])
    tool = WebSearchTool(_StubRegistry(provider))  # type: ignore[arg-type]

    raw = await tool.execute({"query": "hello", "n": 2}, _ctx())
    parsed = json.loads(raw)

    assert parsed == [
        {"title": "A", "url": "https://a", "snippet": "snip A"},
        {"title": "B", "url": "https://b", "snippet": "snip B"},
    ]
    assert provider.last_call == ("hello", 2)


@pytest.mark.asyncio
async def test_search_default_n_is_5() -> None:
    provider = _StubProvider([
        SearchResult(title=f"r{i}", url=f"https://x/{i}", snippet="") for i in range(7)
    ])
    tool = WebSearchTool(_StubRegistry(provider))  # type: ignore[arg-type]

    await tool.execute({"query": "any"}, _ctx())
    assert provider.last_call == ("any", 5)


@pytest.mark.asyncio
async def test_search_clamps_n_to_range() -> None:
    provider = _StubProvider([])
    tool = WebSearchTool(_StubRegistry(provider))  # type: ignore[arg-type]

    await tool.execute({"query": "x", "n": 99}, _ctx())
    assert provider.last_call == ("x", 10)  # capped at max=10

    await tool.execute({"query": "x", "n": 0}, _ctx())
    assert provider.last_call == ("x", 1)   # floored at min=1
