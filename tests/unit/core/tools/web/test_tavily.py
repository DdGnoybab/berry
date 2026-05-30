"""Unit tests for TavilyProvider — assert it adapts the SDK shape correctly.

The real Tavily HTTP call is replaced with a FakeAsyncTavilyClient.
"""

from __future__ import annotations

import pytest

from berry.core.tools.web.providers import tavily as tavily_module
from berry.core.tools.web.providers.tavily import TavilyProvider
from tests._fakes.tavily_fake import FakeAsyncTavilyClient


@pytest.mark.asyncio
async def test_search_returns_search_result_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[FakeAsyncTavilyClient] = []

    def factory(*, api_key: str) -> FakeAsyncTavilyClient:
        client = FakeAsyncTavilyClient(api_key=api_key)
        captured.append(client)
        return client

    monkeypatch.setattr(tavily_module, "AsyncTavilyClient", factory)

    provider = TavilyProvider(api_key="dev-key")
    results = await provider.search("LangGraph", n=2)

    assert len(results) == 2
    assert results[0].title == "LangGraph official tutorial"
    assert results[0].url.startswith("https://")
    assert "tutorial" in results[0].snippet.lower()

    # Verify the fake recorded the call with the right shape.
    assert len(captured) == 1
    assert captured[0].calls == [
        {
            "query": "LangGraph",
            "max_results": 2,
            "search_depth": "basic",
            "timeout": 15.0,
        }
    ]


@pytest.mark.asyncio
async def test_search_passes_through_n_within_provider_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tavily_module,
        "AsyncTavilyClient",
        lambda *, api_key: FakeAsyncTavilyClient(api_key=api_key),
    )

    provider = TavilyProvider(api_key="dev-key")
    results = await provider.search("any", n=10)

    # Default fake has 3 entries; max_results > pool size returns all 3.
    assert len(results) == 3
