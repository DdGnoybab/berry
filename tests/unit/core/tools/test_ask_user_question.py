"""Tests for the ask_user_question tool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from berry.core.agent.event_bus import (
    SuggestionEmitted,
    get_event_bus,
    reset_event_bus_for_testing,
)
from berry.core.agent.suggestion_registry import (
    get_suggestion_registry,
    reset_suggestion_registry_for_testing,
)
from berry.core.tools.base import ToolContext
from berry.core.tools.core.ask_user_question import AskUserQuestionTool


@pytest.fixture(autouse=True)
def _fresh_state() -> None:
    reset_event_bus_for_testing()
    reset_suggestion_registry_for_testing()


def _ctx(session_id: str = "s1") -> ToolContext:
    return ToolContext(
        session_id=session_id,
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp"),
        cwd=Path("/tmp"),
    )


async def test_emits_suggestion_to_event_bus() -> None:
    tool = AskUserQuestionTool()
    bus = get_event_bus()
    queue = bus.subscribe("s1")

    result = await tool.execute(
        {
            "question": "Pick one",
            "options": [
                {"label": "A", "recommended": True},
                {"label": "B", "description": "the boring choice"},
            ],
        },
        _ctx(),
    )

    assert "presented 2" in result
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert isinstance(event, SuggestionEmitted)
    assert event.prompt == "Pick one"
    assert len(event.options) == 2
    assert event.options[0].label == "A"
    assert event.options[0].recommended is True
    assert event.options[1].description == "the boring choice"


async def test_records_to_suggestion_registry() -> None:
    tool = AskUserQuestionTool()
    bus = get_event_bus()
    queue = bus.subscribe("s1")

    await tool.execute(
        {
            "question": "?",
            "options": [{"label": "X"}, {"label": "Y"}],
        },
        _ctx(),
    )
    event = await asyncio.wait_for(queue.get(), timeout=1.0)

    reg = get_suggestion_registry()
    found = reg.lookup(session_id="s1", suggestion_id=event.suggestion_id)
    assert found is not None
    assert [o["label"] for o in found] == ["X", "Y"]


async def test_no_options_returns_no_op_message() -> None:
    tool = AskUserQuestionTool()
    bus = get_event_bus()
    queue = bus.subscribe("s1")
    result = await tool.execute({"question": "?", "options": []}, _ctx())
    assert "no valid options" in result
    assert queue.empty()


async def test_each_call_gets_a_fresh_suggestion_id() -> None:
    tool = AskUserQuestionTool()
    bus = get_event_bus()
    queue = bus.subscribe("s1")

    args = {"question": "?", "options": [{"label": "A"}, {"label": "B"}]}
    await tool.execute(args, _ctx())
    await tool.execute(args, _ctx())

    e1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    e2 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert e1.suggestion_id != e2.suggestion_id
