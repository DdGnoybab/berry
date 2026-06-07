"""EventBus — channel-agnostic per-session pub/sub for agent events.

The agent engine (``ConversationRuntime``, tools) emits events here.
Channels (web SSE, feishu cards, CLI renderer) subscribe per-session
and translate events into their own output formats.

Why this lives in ``core/agent/`` (not ``core/``):
  - It carries ``BerryEvent`` which is `agent_events.AgentEvent` plus
    a few channel-relevant additions (``SuggestionEmitted``).
  - ``core/`` doesn't know about channels — channel just subscribes
    and renders. EventBus has no SSE knowledge, no card knowledge.

Replaces the SSE-shaped ``suggestion_event.py`` queue (ADR-0010).

Concurrency model:
  - One ``asyncio.Queue`` per session; ``subscribe`` registers it,
    ``unsubscribe`` removes.
  - Multiple subscribers per session are allowed (each gets its own
    queue) — feishu card listener + web SSE can both watch the same
    session if the session crosses channels.
  - ``emit`` is non-blocking; ``put_nowait`` skipped if no subscriber.
  - Backed by in-memory state — fine for single-process MVP.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from berry.core.agent import events as agent_events
from berry.observability.logging import get_logger

logger = get_logger(__name__)


# ── Event types channels can subscribe to ─────────────────────────────


@dataclass
class SuggestionOption:
    """One clickable option presented to the user."""

    label: str
    description: str | None = None
    recommended: bool = False


@dataclass
class SuggestionEmitted:
    """Emitted when a tool (currently ``ask_user_question``) wants the
    UI to show clickable buttons.

    Channel-agnostic: web turns this into an SSE event, feishu turns it
    into a card. Carries no channel-specific fields (no SSE format,
    no card schema).
    """

    type: str = "suggestion_emitted"
    suggestion_id: str = ""
    """Stable ID for this round; channels echo it back on click for
    stale-detection in ``SuggestionRegistry``."""
    prompt: str = ""
    options: list[SuggestionOption] = field(default_factory=list)


# Union of everything channels might want to observe.
# Currently overlaps with ``AgentEvent`` but stays separate so we can
# add channel-only events (SuggestionEmitted) without polluting the
# LLM-loop's event stream.
BerryEvent = agent_events.AgentEvent | SuggestionEmitted


# ── Per-session pub/sub ───────────────────────────────────────────────


class EventBus:
    """Per-session async event bus.

    Subscribers receive events via an ``AsyncIterator``. Multiple
    subscribers per session are allowed (each owns a queue).
    """

    def __init__(self) -> None:
        # session_id -> list of queues (one per subscriber)
        self._queues: dict[str, list[asyncio.Queue[BerryEvent | None]]] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue[BerryEvent | None]:
        """Register a subscriber. Returns the queue it should drain.

        Caller is responsible for calling ``unsubscribe`` on cleanup.
        """
        q: asyncio.Queue[BerryEvent | None] = asyncio.Queue()
        self._queues.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(
        self, session_id: str, queue: asyncio.Queue[BerryEvent | None]
    ) -> None:
        """Remove a subscriber."""
        queues = self._queues.get(session_id)
        if not queues:
            return
        try:
            queues.remove(queue)
        except ValueError:
            pass
        if not queues:
            self._queues.pop(session_id, None)

    def emit(self, session_id: str, event: BerryEvent) -> None:
        """Push event to every subscriber on this session.

        Non-blocking. If no one is subscribed, the event is dropped
        silently (this is fine for ephemeral UI events; persistent
        state lives elsewhere).
        """
        queues = self._queues.get(session_id)
        if not queues:
            return
        for q in queues:
            try:
                q.put_nowait(event)
            except Exception as exc:
                logger.warning(
                    "event_bus_emit_failed",
                    session_id=session_id,
                    event_type=getattr(event, "type", type(event).__name__),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

    async def drain(self, session_id: str) -> AsyncIterator[BerryEvent]:
        """Async-iterate events for a session. Subscribes on enter,
        unsubscribes on exit. Stops when ``None`` is enqueued or the
        coroutine is cancelled.
        """
        q = self.subscribe(session_id)
        try:
            while True:
                event = await q.get()
                if event is None:
                    break
                yield event
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(session_id, q)


# ── Process-wide default bus ──────────────────────────────────────────

_default_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the process-wide default EventBus."""
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus


def reset_event_bus_for_testing() -> None:
    """Tests use this to get a fresh bus between cases."""
    global _default_bus
    _default_bus = None


# ── Convenience: emit a SuggestionEmitted ─────────────────────────────


def emit_suggestion(
    session_id: str,
    *,
    suggestion_id: str,
    prompt: str,
    options: list[SuggestionOption],
) -> None:
    """Shortcut: emit a SuggestionEmitted on the default bus."""
    get_event_bus().emit(
        session_id,
        SuggestionEmitted(
            suggestion_id=suggestion_id,
            prompt=prompt,
            options=list(options),
        ),
    )


# ── Public API ────────────────────────────────────────────────────────

__all__ = [
    "BerryEvent",
    "EventBus",
    "SuggestionEmitted",
    "SuggestionOption",
    "emit_suggestion",
    "get_event_bus",
    "reset_event_bus_for_testing",
]
