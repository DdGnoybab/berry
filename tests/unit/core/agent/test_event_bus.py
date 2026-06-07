"""EventBus pub/sub semantics."""

from __future__ import annotations

import asyncio

import pytest

from berry.core.agent.event_bus import (
    EventBus,
    SuggestionEmitted,
    SuggestionOption,
    emit_suggestion,
    get_event_bus,
    reset_event_bus_for_testing,
)


@pytest.fixture(autouse=True)
def _fresh_bus() -> None:
    reset_event_bus_for_testing()


async def _drain_some(bus: EventBus, session_id: str, n: int) -> list:
    """Take up to n events from the bus, then close."""
    out = []
    queue = bus.subscribe(session_id)
    try:
        for _ in range(n):
            ev = await asyncio.wait_for(queue.get(), timeout=1.0)
            out.append(ev)
    finally:
        bus.unsubscribe(session_id, queue)
    return out


async def test_emit_to_single_subscriber() -> None:
    bus = EventBus()
    queue = bus.subscribe("s1")
    bus.emit("s1", SuggestionEmitted(suggestion_id="x", prompt="?"))
    ev = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert isinstance(ev, SuggestionEmitted)
    assert ev.suggestion_id == "x"


async def test_emit_with_no_subscriber_drops_silently() -> None:
    bus = EventBus()
    bus.emit("ghost", SuggestionEmitted(suggestion_id="y", prompt="?"))
    # No exception, no listeners.


async def test_two_subscribers_each_get_their_copy() -> None:
    bus = EventBus()
    q1 = bus.subscribe("s1")
    q2 = bus.subscribe("s1")
    bus.emit("s1", SuggestionEmitted(suggestion_id="z", prompt="?"))
    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1.suggestion_id == "z"
    assert e2.suggestion_id == "z"


async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    q = bus.subscribe("s1")
    bus.unsubscribe("s1", q)
    bus.emit("s1", SuggestionEmitted(suggestion_id="z", prompt="?"))
    assert q.empty()


async def test_session_isolation() -> None:
    bus = EventBus()
    qa = bus.subscribe("s_a")
    qb = bus.subscribe("s_b")
    bus.emit("s_a", SuggestionEmitted(suggestion_id="aa", prompt="?"))
    bus.emit("s_b", SuggestionEmitted(suggestion_id="bb", prompt="?"))
    ea = await asyncio.wait_for(qa.get(), timeout=1.0)
    eb = await asyncio.wait_for(qb.get(), timeout=1.0)
    assert ea.suggestion_id == "aa"
    assert eb.suggestion_id == "bb"


async def test_emit_suggestion_helper_writes_via_default_bus() -> None:
    bus = get_event_bus()
    q = bus.subscribe("s1")
    emit_suggestion(
        "s1",
        suggestion_id="hello",
        prompt="pick",
        options=[SuggestionOption(label="A"), SuggestionOption(label="B", recommended=True)],
    )
    ev = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(ev, SuggestionEmitted)
    assert ev.suggestion_id == "hello"
    assert ev.prompt == "pick"
    assert len(ev.options) == 2
    assert ev.options[1].recommended is True
