"""Parse SESSION_LOG.md (Berry Learning Loop's append-only journal) into entries.

Format spec:
  docs/superpowers/specs/2026-06-01-learning-loop-product-design.md
  (revised in dogfood iteration §6.4 — "Session continuity")

Each entry is an H2-rooted block:

  ## YYYY-MM-DD HH:MM (session <session-id>)
  - <free-form bullets>
  - Pending: <something unfinished, optional>
  - User signal: <user feedback, optional>

The parser walks H2 headers with the regex shape ``(session <id>)`` and
slices the content between consecutive headers as the entry body.

Tolerance philosophy: garbage in returns ``[]`` rather than raising —
LLM falls back to reading SESSION_LOG.md raw if it cares.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionLogEntry:
    """One block in SESSION_LOG.md."""

    timestamp: str            # "YYYY-MM-DD HH:MM"
    session_id: str           # the inner ID, no parens
    body: str                 # bullet lines joined, leading hyphens kept
    has_pending: bool         # True if "Pending:" or "Issue:" appears in body


# H2 header form: ## <YYYY-MM-DD HH:MM> (session <id>)
_HEADER_RE = re.compile(
    r"^##\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+\(session\s+([^)]+)\)\s*$",
    re.MULTILINE,
)

_PENDING_RE = re.compile(r"^\s*-\s*(Pending|Issue):", re.MULTILINE)


def parse_session_log_md(content: str) -> list[SessionLogEntry]:
    """Parse SESSION_LOG.md content into a list of entries (in file order).

    Returns ``[]`` for empty content, no recognized headers, or any parse
    irregularity. The list is ordered by appearance in the file (which is
    chronological because SESSION_LOG.md is append-only).
    """
    if not content.strip():
        return []

    matches = list(_HEADER_RE.finditer(content))
    if not matches:
        return []

    entries: list[SessionLogEntry] = []
    for i, m in enumerate(matches):
        timestamp, session_id = m.group(1), m.group(2)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[body_start:body_end].strip()
        has_pending = bool(_PENDING_RE.search(body))
        entries.append(
            SessionLogEntry(
                timestamp=timestamp,
                session_id=session_id.strip(),
                body=body,
                has_pending=has_pending,
            )
        )

    return entries


__all__ = [
    "SessionLogEntry",
    "parse_session_log_md",
]
