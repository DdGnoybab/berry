"""Subscribe to ``EventBus`` and render Feishu cards for relevant events.

After ADR-0010, the agent engine emits ``SuggestionEmitted`` events whenever
the LLM calls ``ask_user_question``. This listener:

  1. For each session that has a Feishu chat context, subscribes a queue.
  2. Renders ``SuggestionEmitted`` as a SUGGEST card and sends it.
  3. Optionally renders other event types (currently no-op).

Replaces the old ``progress_watcher`` reconciler, which read
``progress.json`` and inferred SUGGEST events. ADR-0010 makes the LLM
emit suggestions directly via tool calls — no file watch needed.

Subscription strategy:
  Eagerly subscribe per session_id when the FeishuRuntimeAdapter sees
  its first turn for that session. Keep subscribed until process exit
  (no per-turn unsubscribe — events can fire post-turn during sub-menu
  follow-ups). One ``asyncio.Task`` per session drains its queue.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol

from berry.channels.feishu import send as send_mod
from berry.channels.feishu.cards.suggest_card import build_suggest_card
from berry.core.agent.event_bus import (
    BerryEvent,
    SuggestionEmitted,
    get_event_bus,
)
from berry.core.agent.suggestion_registry import get_suggestion_registry
from berry.observability.logging import get_logger

if TYPE_CHECKING:
    import lark_oapi as lark

logger = get_logger(__name__)


class _ChatResolver(Protocol):
    """Closure ``session_id -> (chat_id, user_open_id, trigger_message_id)``."""

    def __call__(
        self, session_id: str
    ) -> tuple[str | None, str | None, str | None]: ...


class FeishuEventListener:
    """Per-process listener that subscribes to EventBus and translates
    SuggestionEmitted events into Feishu cards.

    Holds one drain task per active session_id. Tasks live until the
    process exits.
    """

    def __init__(
        self,
        *,
        lark_client: lark.Client,
        chat_resolver: _ChatResolver,
    ) -> None:
        self._client = lark_client
        self._resolve = chat_resolver
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def ensure_subscribed(self, session_id: str) -> None:
        """Idempotent. Call when a session enters Feishu (e.g. at the
        start of a turn) to ensure we'll deliver any future events.
        """
        if session_id in self._tasks:
            return
        bus = get_event_bus()
        queue = bus.subscribe(session_id)
        task = asyncio.create_task(
            self._drain(session_id, queue),
            name=f"feishu-events-{session_id[:8]}",
        )
        self._tasks[session_id] = task

    async def _drain(
        self,
        session_id: str,
        queue: asyncio.Queue[BerryEvent | None],
    ) -> None:
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                self._handle(session_id, event)
        except asyncio.CancelledError:
            pass
        finally:
            get_event_bus().unsubscribe(session_id, queue)
            self._tasks.pop(session_id, None)

    def _handle(self, session_id: str, event: BerryEvent) -> None:
        if isinstance(event, SuggestionEmitted):
            self._render_suggest(session_id, event)
        # Other event types (text_delta / tool_call / etc.) currently
        # not rendered to Feishu — runtime_adapter handles those
        # synchronously inside its run_turn loop.

    def _render_suggest(self, session_id: str, event: SuggestionEmitted) -> None:
        chat_id, user_open_id, trigger_message_id = self._resolve(session_id)
        if not chat_id:
            logger.debug(
                "feishu_suggest_skipped_no_chat",
                session_id=session_id,
            )
            return

        # Record this suggestion so click_handler can validate stale clicks.
        get_suggestion_registry().record(
            session_id=session_id,
            suggestion_id=event.suggestion_id,
            options=[
                {
                    "label": o.label,
                    "description": o.description,
                    "recommended": o.recommended,
                }
                for o in event.options
            ],
        )

        try:
            card_json = build_suggest_card(
                suggestion_id=event.suggestion_id,
                prompt=event.prompt,
                options=[
                    {
                        "label": o.label,
                        "description": o.description,
                        "recommended": o.recommended,
                    }
                    for o in event.options
                ],
                user_open_id=user_open_id,
                chat_id=chat_id,
            )
        except Exception as exc:
            logger.warning(
                "feishu_suggest_card_build_failed",
                session_id=session_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return

        send_mod.send_approval_card(
            self._client,
            chat_id=chat_id,
            card_json=card_json,
            reply_to_message_id=trigger_message_id,
        )


_default_listener: FeishuEventListener | None = None


def install_feishu_event_listener(
    *,
    lark_client: lark.Client,
    chat_resolver: _ChatResolver,
) -> FeishuEventListener:
    """One-shot: register the process-wide Feishu listener.

    Called from ``entrypoints/feishu.py`` after the runtime adapter is built.
    """
    global _default_listener
    _default_listener = FeishuEventListener(
        lark_client=lark_client,
        chat_resolver=chat_resolver,
    )
    return _default_listener


def get_feishu_event_listener() -> FeishuEventListener | None:
    """Process-wide listener handle — channels/feishu/runtime_adapter
    calls this to ``ensure_subscribed`` on each new session.
    """
    return _default_listener
