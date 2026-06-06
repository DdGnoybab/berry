"""progress.json reconciler — emit SUGGEST events when LLM produces a new suggestion.

Why a reconciler instead of a tool-call hook?
  - SKILL.md tells the LLM to ``edit_file .berry/progress.json`` after every
    state transition. We don't want to specialize the generic ``edit_file``
    tool with learning-specific logic (that violates berry's "no business
    tools" red line in CLAUDE.md).
  - Instead, after each turn ends, we read progress.json fresh and compare
    its ``current.last_suggestion.produced_at`` against the cached "last
    seen" timestamp. A new produced_at means the LLM emitted a new SUGGEST
    this turn — fire the event.
  - This keeps learning concerns in ``berry/assistants/learning/`` per
    CLAUDE.md §2 (assistants self-contained), and reuses the existing
    ``todo_event``-style listener pattern.

Compared to a true file-watch (watchdog/inotify): a per-turn reconciler is
sufficient because progress.json is only written by the LLM during a turn,
and we only need to render its output between turns. Saves the dependency.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from berry.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SuggestEmittedEvent:
    """Fired when ``progress.json.current.last_suggestion`` is new since the
    previous reconciliation tick.

    The full suggestion dict is included so the listener can render the
    SUGGEST card without re-reading the file.
    """

    conversation_id: str
    workspace_path: Path
    topic: str | None
    atom: str | None
    suggestion: dict[str, Any]
    """The full ``current.last_suggestion`` block from progress.json:
    ``{produced_at, context, score, weak_points, options, sub_menu, ...}``.
    """


SuggestListener = Callable[[SuggestEmittedEvent], None]


class ProgressWatcher:
    """Per-conversation reconciler.

    Holds a cache of last seen ``produced_at`` per ``conversation_id`` so
    we only emit when the SUGGEST is genuinely new. The cache is in-memory
    only — restart loses it, but that just means the first turn after restart
    might re-emit a stale SUGGEST card, which is harmless (user clicks the
    button → runtime sees the choice → state advances).

    Use ``register_listener`` to subscribe; call ``reconcile`` at every
    turn-end with the workspace path that owns this conversation.
    """

    def __init__(self) -> None:
        self._listeners: list[SuggestListener] = []
        # conversation_id -> last seen produced_at (ISO string)
        self._last_seen: dict[str, str | None] = {}

    def register_listener(self, listener: SuggestListener) -> None:
        self._listeners.append(listener)

    def reconcile(self, *, conversation_id: str, workspace_path: Path) -> None:
        """Read progress.json under ``workspace_path``, fire event if SUGGEST is new.

        Robust to: missing file (no progress yet), malformed JSON, missing
        keys. Any of those cases are treated as "no SUGGEST to emit".
        """
        progress_path = workspace_path / ".berry" / "progress.json"
        if not progress_path.is_file():
            return
        try:
            data = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "progress_json_read_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                path=str(progress_path),
            )
            return

        current = data.get("current") or {}
        suggestion = current.get("last_suggestion")
        if not suggestion:
            return
        produced_at = suggestion.get("produced_at")
        if not produced_at:
            return

        last = self._last_seen.get(conversation_id)
        if last == produced_at:
            return  # nothing new this turn

        self._last_seen[conversation_id] = produced_at

        topic = data.get("topic")
        atom = current.get("atom")
        event = SuggestEmittedEvent(
            conversation_id=conversation_id,
            workspace_path=workspace_path,
            topic=topic,
            atom=atom,
            suggestion=suggestion,
        )
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as exc:  # noqa: BLE001 — fire-and-forget
                logger.warning(
                    "suggest_listener_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )


_default_watcher: ProgressWatcher | None = None


def get_default_watcher() -> ProgressWatcher:
    """Process-wide default watcher. Channels register listeners on this."""
    global _default_watcher
    if _default_watcher is None:
        _default_watcher = ProgressWatcher()
    return _default_watcher


def reset_default_watcher_for_testing() -> None:
    """Tests use this to get a fresh watcher between cases."""
    global _default_watcher
    _default_watcher = None
