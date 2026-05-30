"""WebFetchTool — fetch a URL, naive HTML→text strip, return JSON.

Modeled after claw-code's web_fetch (rust/crates/tools/src/lib.rs:3188+):
no markdown library, no DOM parsing — a simple character-level "in-tag /
out-of-tag" stripper, with whitespace collapsing. The output is plain text
that downstream LLM calls can quote into ``write_md`` content.

Why this minimalism (vs trafilatura/readability):
- Zero dependencies on top of httpx.
- Stable: nothing to break when a parser library bumps a major version.
- "Good enough": berry's flow re-asks the LLM to compose .md files from the
  fetched content, so the LLM filters noise itself. Pre-cleaning isn't
  worth a heavyweight parser.
"""

from __future__ import annotations

import json
import re
import time
from http import HTTPStatus
from typing import Any, ClassVar

import httpx

from berry.core.tools.base import ToolContext

_USER_AGENT = "berry/0.0.3 (+https://github.com)"

# Cap LLM context cost. 30k chars ≈ 8-10k tokens — enough for one article,
# small enough that two fetches still leave room for a tool_use turn.
_MAX_CHARS = 30_000

# match a <title>...</title> in case-insensitive, non-greedy form
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class WebFetchTool:
    name: ClassVar[str] = "web_fetch"
    description: ClassVar[str] = (
        "Fetch a URL over HTTP. For HTML, strips tags and collapses whitespace "
        "to a plain-text body. Use after web_search when you want the actual "
        "page contents (not just the snippet) — e.g. to extract code examples, "
        "definitions, or longer prose. Returns JSON with the fetched content."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (http:// or https://).",
            },
        },
        "required": ["url"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        url = str(args["url"]).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError(f"web_fetch only supports http(s) urls, got {url!r}")

        started = time.monotonic()
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = await client.get(url)
        body = response.text
        content_type = response.headers.get("content-type", "").lower()

        if "html" in content_type:  # noqa: SIM108 — explicit branches read clearer than ternary here
            result_text = _strip_html_tags(body)
        else:
            result_text = body.strip()

        truncated = False
        if len(result_text) > _MAX_CHARS:
            result_text = result_text[:_MAX_CHARS] + "\n\n[truncated]"
            truncated = True

        title = _extract_title(body) if "html" in content_type else None

        payload = {
            "url": str(response.url),
            "code": response.status_code,
            "codeText": _phrase_for(response.status_code),
            "bytes": len(body),
            "durationMs": int((time.monotonic() - started) * 1000),
            "title": title,
            "result": result_text,
            "truncated": truncated,
        }
        return json.dumps(payload, ensure_ascii=False)


# ─── helpers ────────────────────────────────────────────────────────────


def _strip_html_tags(html: str) -> str:
    """claw-code-style strip: walk the string, drop characters between
    ``<`` and ``>``, collapse whitespace runs to a single space.
    """
    out: list[str] = []
    in_tag = False
    previous_was_space = False
    for ch in html:
        if ch == "<":
            in_tag = True
            continue
        if ch == ">":
            in_tag = False
            continue
        if in_tag:
            continue
        if ch.isspace():
            if not previous_was_space:
                out.append(" ")
                previous_was_space = True
        else:
            out.append(ch)
            previous_was_space = False
    return "".join(out).strip()


def _extract_title(html: str) -> str | None:
    """Pull the first <title>…</title> if present. Naive but matches what
    99% of pages emit; we don't try to handle <head> in <body> nightmares.
    """
    match = _TITLE_RE.search(html)
    if not match:
        return None
    raw = match.group(1).strip()
    # strip stray inner tags / whitespace runs the same way as body text
    return _strip_html_tags(raw) or None


def _phrase_for(code: int) -> str:
    try:
        return HTTPStatus(code).phrase
    except ValueError:
        return "Unknown"
