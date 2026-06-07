"""SuggestionRegistry — per-session record of recently emitted suggestions.

Used by Feishu's card click handler (and any future channel needing
the same) to:

  - Detect stale clicks (user clicks an old card after the LLM has
    already moved on to a newer suggestion).
  - Validate that the clicked label was actually one of the offered
    options.

This replaces the old ``progress.json.last_suggestion`` based stale-check
done by ``assistants/learning/click_handler.py``. After ADR-0010 the
LLM no longer writes suggestions to progress.json; the source of truth
is the in-memory record kept here.

Design choices:
  - In-memory only — single-process MVP. Restart loses the registry,
    but that just means clicks on cards from before the restart fall
    through to ``stale``, which matches user expectations.
  - Per-session deque with a fixed max size (default 8). When the LLM
    rapid-fires N suggestions in a turn, only the most recent N are
    valid; older ones are stale. Sized to 8 so a learning turn that
    presents init-flow → goal → roadmap → atom doesn't lose the
    earliest by the time the user clicks.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Entry:
    suggestion_id: str
    options: list[dict[str, Any]]


@dataclass
class SuggestionRegistry:
    """Per-session deque of recently emitted suggestions.

    Bounded by ``maxlen`` per session (default 8).
    """

    maxlen: int = 8
    _by_session: dict[str, deque[_Entry]] = field(default_factory=dict)

    def record(
        self,
        *,
        session_id: str,
        suggestion_id: str,
        options: list[dict[str, Any]],
    ) -> None:
        """Append a new suggestion to the session's deque, evicting the
        oldest if at maxlen.
        """
        dq = self._by_session.get(session_id)
        if dq is None:
            dq = deque(maxlen=self.maxlen)
            self._by_session[session_id] = dq
        dq.append(_Entry(suggestion_id=suggestion_id, options=options))

    def lookup(
        self,
        *,
        session_id: str,
        suggestion_id: str,
    ) -> list[dict[str, Any]] | None:
        """Return the option list for a given suggestion_id within the
        session, or ``None`` if not found / evicted (stale).
        """
        dq = self._by_session.get(session_id)
        if dq is None:
            return None
        for entry in dq:
            if entry.suggestion_id == suggestion_id:
                return entry.options
        return None

    def is_latest(self, *, session_id: str, suggestion_id: str) -> bool:
        """True iff ``suggestion_id`` is the most recently recorded for
        this session.
        """
        dq = self._by_session.get(session_id)
        if not dq:
            return False
        return dq[-1].suggestion_id == suggestion_id


_default_registry: SuggestionRegistry | None = None


def get_suggestion_registry() -> SuggestionRegistry:
    """Process-wide default registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = SuggestionRegistry()
    return _default_registry


def reset_suggestion_registry_for_testing() -> None:
    global _default_registry
    _default_registry = None
