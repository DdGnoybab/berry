"""Feishu CardKit V2 card builder.

Converts LLM markdown output into a V2 card with collapsible sections:

- ``## Heading`` markers become ``collapsible_panel`` components (collapsed by
  default) so long replies stay scannable.
- The first ``# Heading`` (if present) is lifted into the card ``header``.
- Text before any heading becomes a leading markdown element.
- Content with no headings is rendered as a single markdown element (same
  visual as before, just V2 schema).

V2 schema reference:
    https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/feishu-cards/card-json-structure

    {
      "schema": "2.0",
      "header": { "title": { "tag": "plain_text", "content": "..." } },
      "body": { "elements": [ ... ] }
    }
"""

from __future__ import annotations

import json
import re
from typing import Any

# Matches a line that starts with ``## `` (level-2 heading).  We only split on
# level 2 because LLM output almost always uses ``##`` as the primary section
# delimiter; ``###`` and below stay inside the collapsible panel body.
_H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)

# Matches an optional leading ``# Title`` line (level-1).
_H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)


def _md_element(content: str) -> dict[str, Any]:
    return {"tag": "markdown", "content": content}


def _collapsible_panel(title: str, body_md: str) -> dict[str, Any]:
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {"title": {"tag": "plain_text", "content": title}},
        "elements": [_md_element(body_md)],
    }


def build_markdown_card_v2(
    md: str,
    *,
    header_title: str | None = "berry",
    collapse_sections: bool = True,
) -> str:
    """Build a Feishu CardKit V2 interactive card JSON string.

    Parameters
    ----------
    md:
        Raw markdown text (typically the LLM's full output).
    header_title:
        Card header title. If ``None``, no header is emitted.  When the
        markdown itself starts with ``# Title``, that line is consumed and
        used as the header *instead* of ``header_title``.
    collapse_sections:
        If *True* (default), top-level ``## Heading`` lines are converted into
        collapsed ``collapsible_panel`` components.  Set to *False* to render
        everything as flat markdown (useful for very short replies).
    """
    if not collapse_sections:
        return json.dumps(_flat_card(md, header_title=header_title), ensure_ascii=False)

    # --- try lifting the first ``# Title`` into the card header ---
    h1_match = _H1_RE.search(md)
    if h1_match:
        header_title = h1_match.group(1).strip()
        md = md[: h1_match.start()] + md[h1_match.end() :]

    # --- split on ``## `` headings ---
    parts: list[str] = _H2_RE.split(md)
    # ``re.split`` with a capturing group yields:
    #   [pre, title1, body1, title2, body2, ...]

    elements: list[dict[str, Any]] = []

    if len(parts) == 1:
        # No ``##`` headings at all — flat markdown.
        elements.append(_md_element(parts[0].strip()))
    else:
        # Leading text before the first ``##``
        pre = parts[0].strip()
        if pre:
            elements.append(_md_element(pre))
        it = iter(parts[1:])
        for title, body in zip(it, it, strict=False):
            title = title.strip()
            body = body.strip()
            if not title and not body:
                continue
            elements.append(_collapsible_panel(title, body))

    card: dict[str, Any] = {
        "schema": "2.0",
        "body": {"elements": elements},
    }

    if header_title is not None:
        card["header"] = {
            "title": {"tag": "plain_text", "content": header_title},
            "template": "blue",
        }

    return json.dumps(card, ensure_ascii=False)


def _flat_card(md: str, *, header_title: str | None) -> dict[str, Any]:
    """Fallback: single-element V2 card (no collapsible sections)."""
    card: dict[str, Any] = {
        "schema": "2.0",
        "body": {"elements": [_md_element(md)]},
    }
    if header_title is not None:
        card["header"] = {
            "title": {"tag": "plain_text", "content": header_title},
            "template": "blue",
        }
    return card
