"""Unit tests for WebFetchTool — strip-tags / title extraction / truncation.

Network calls themselves are NOT exercised here (those would be flaky and
slow). We instead test the pure functions and exercise the http client via
``httpx.MockTransport`` so we can drive specific status codes / bodies.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from berry.core.tools.base import ToolContext
from berry.core.tools.web.fetch import WebFetchTool, _extract_title, _strip_html_tags

# ─── pure functions ─────────────────────────────────────────────────────


def test_strip_html_tags_removes_simple_tags() -> None:
    out = _strip_html_tags("<p>hello <b>world</b></p>")
    assert out == "hello world"


def test_strip_html_tags_collapses_whitespace() -> None:
    out = _strip_html_tags("<div>line1\n\n\n\nline2</div>")
    assert out == "line1 line2"


def test_strip_html_tags_handles_nested_and_attributes() -> None:
    html = '<a href="x" class="y">click <span>here</span></a>'
    out = _strip_html_tags(html)
    assert out == "click here"


def test_extract_title_from_typical_html() -> None:
    html = "<html><head><title>Berry Demo</title></head><body>x</body></html>"
    assert _extract_title(html) == "Berry Demo"


def test_extract_title_returns_none_when_missing() -> None:
    assert _extract_title("<html><body>no title here</body></html>") is None


def test_extract_title_handles_multiline_content() -> None:
    html = "<html><head>\n<title>\n  Multiline\n  Title\n</title>\n</head></html>"
    out = _extract_title(html)
    assert out == "Multiline Title"


# ─── execute() with MockTransport ──────────────────────────────────────


def _ctx() -> ToolContext:
    return ToolContext(
        session_id=uuid4(),
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp/berry_test"),
    )


@pytest.mark.asyncio
async def test_execute_html_response_strips_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "<html><head><title>T</title></head><body><p>Hello <b>world</b></p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    transport = httpx.MockTransport(handler)
    _patch_async_client_with(monkeypatch, transport)

    tool = WebFetchTool()
    raw = await tool.execute({"url": "https://example.com/"}, _ctx())
    payload = json.loads(raw)

    assert payload["code"] == 200
    assert payload["codeText"] == "OK"
    assert payload["title"] == "T"
    # Note: claw-code-style strip walks the entire document, so the title
    # text reappears in `result` ahead of the body. That's accepted —
    # LLMs read it as one stream of prose.
    assert "Hello world" in payload["result"]
    assert payload["truncated"] is False
    assert payload["bytes"] == len(body)


@pytest.mark.asyncio
async def test_execute_non_html_response_returns_body_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = '{"hello": "world"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=body, headers={"content-type": "application/json"}
        )

    transport = httpx.MockTransport(handler)
    _patch_async_client_with(monkeypatch, transport)

    tool = WebFetchTool()
    raw = await tool.execute({"url": "https://example.com/api"}, _ctx())
    payload = json.loads(raw)

    assert payload["result"] == body
    assert payload["title"] is None


@pytest.mark.asyncio
async def test_execute_truncates_long_html(monkeypatch: pytest.MonkeyPatch) -> None:
    long_text = "x" * 60_000
    body = f"<html><body><p>{long_text}</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    _patch_async_client_with(monkeypatch, transport)

    tool = WebFetchTool()
    raw = await tool.execute({"url": "https://example.com/big"}, _ctx())
    payload = json.loads(raw)

    assert payload["truncated"] is True
    assert payload["result"].endswith("[truncated]")
    # Within the cap (30k) plus the marker.
    assert len(payload["result"]) <= 30_000 + len("\n\n[truncated]")


@pytest.mark.asyncio
async def test_execute_rejects_non_http_url() -> None:
    tool = WebFetchTool()
    with pytest.raises(ValueError, match="http"):
        await tool.execute({"url": "ftp://example.com/file"}, _ctx())


# ─── helpers ────────────────────────────────────────────────────────────


def _patch_async_client_with(
    monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport
) -> None:
    """Replace ``httpx.AsyncClient`` (as imported by fetch.py) with a
    factory that always wires our MockTransport. We capture the original
    class object BEFORE patching so the factory can still build a real
    AsyncClient — patching the symbol with itself would recurse.
    """
    real_async_client = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("berry.core.tools.web.fetch.httpx.AsyncClient", factory)
