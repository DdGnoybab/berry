"""Translate ``BerryEvent``s on the EventBus into SSE frames for the
web frontend.

The runtime emits ``AgentEvent``s (turn_start / text_delta / tool_call /
tool_result / turn_end) and tools emit ``SuggestionEmitted`` —
this adapter:

  1. Subscribes to the EventBus for one session.
  2. Drains events.
  3. Serialises each into JSON and wraps in ``data: ...\\n\\n`` SSE format.

Channel-specific knowledge (SSE wire format, JSON shape the frontend
expects) lives here, NOT in core. Core just emits typed events.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from berry.core.agent.event_bus import (
    BerryEvent,
    SuggestionEmitted,
    get_event_bus,
)


def serialize_event(event: BerryEvent) -> str:
    """Convert an event to the JSON payload the frontend expects.

    Frontend types live in ``web/src/types.ts``. Two event families:

    - Pydantic ``AgentEvent`` (turn_start / text_delta / tool_call_start /
      tool_result / turn_end / approval_asked) — already has ``type``
      discriminator; ``model_dump`` gives the right shape.
    - ``SuggestionEmitted`` (dataclass) — manually serialise.
    """
    if isinstance(event, SuggestionEmitted):
        return json.dumps(
            {
                "type": "suggestion_emitted",
                "suggestion_id": event.suggestion_id,
                "prompt": event.prompt,
                "options": [
                    {
                        "label": o.label,
                        "description": o.description,
                        "recommended": o.recommended,
                    }
                    for o in event.options
                ],
            },
            ensure_ascii=False,
        )

    # AgentEvent — Pydantic models, dump straight to JSON
    if hasattr(event, "model_dump_json"):
        return event.model_dump_json()  # type: ignore[no-any-return]

    # Defensive fallback — should never hit if BerryEvent stays well-typed
    return json.dumps({"type": "unknown", "repr": repr(event)})


async def stream_session_events(session_id: str) -> AsyncIterator[str]:
    """Yield SSE-formatted strings for every event emitted on
    ``session_id``. Subscribes on entry, unsubscribes on exit.

    The caller wraps the result in a ``StreamingResponse``.
    """
    bus = get_event_bus()
    async for event in bus.drain(session_id):
        data = serialize_event(event)
        yield f"data: {data}\n\n"
