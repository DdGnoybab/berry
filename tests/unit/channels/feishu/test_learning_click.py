"""Tests for the new feishu learning_click.process_click — pure logic.

Validates against an in-memory SuggestionRegistry (no progress.json
involved after ADR-0010).
"""

from __future__ import annotations

from berry.channels.feishu.learning_click import process_click
from berry.core.agent.suggestion_registry import SuggestionRegistry


def _populated_registry() -> SuggestionRegistry:
    reg = SuggestionRegistry()
    reg.record(
        session_id="s1",
        suggestion_id="sg_001",
        options=[
            {"label": "完整重讲", "recommended": True},
            {"label": "只补漏点"},
            {"label": "我懂了"},
        ],
    )
    return reg


def test_pick_option_synthesizes_message_with_label() -> None:
    reg = _populated_registry()
    decision = process_click(
        session_id="s1",
        metadata={"suggestion_id": "sg_001", "label": "完整重讲"},
        registry=reg,
    )
    assert decision.kind == "pick_option"
    assert decision.chosen_label == "完整重讲"
    assert decision.was_recommended is True
    assert decision.synthesized_user_message == "完整重讲"


def test_pick_non_recommended_option_flags_was_recommended_false() -> None:
    reg = _populated_registry()
    decision = process_click(
        session_id="s1",
        metadata={"suggestion_id": "sg_001", "label": "只补漏点"},
        registry=reg,
    )
    assert decision.kind == "pick_option"
    assert decision.was_recommended is False


def test_stale_when_suggestion_id_not_in_registry() -> None:
    reg = _populated_registry()
    decision = process_click(
        session_id="s1",
        metadata={"suggestion_id": "sg_unknown", "label": "完整重讲"},
        registry=reg,
    )
    assert decision.kind == "stale"


def test_stale_when_session_has_no_entries() -> None:
    reg = SuggestionRegistry()
    decision = process_click(
        session_id="s_empty",
        metadata={"suggestion_id": "sg_001", "label": "完整重讲"},
        registry=reg,
    )
    assert decision.kind == "stale"


def test_unknown_label_in_recorded_options() -> None:
    reg = _populated_registry()
    decision = process_click(
        session_id="s1",
        metadata={"suggestion_id": "sg_001", "label": "does-not-exist"},
        registry=reg,
    )
    assert decision.kind == "unknown_label"


def test_missing_suggestion_id_in_metadata() -> None:
    reg = _populated_registry()
    decision = process_click(
        session_id="s1",
        metadata={"label": "完整重讲"},
        registry=reg,
    )
    assert decision.kind == "unknown_label"


def test_missing_label_in_metadata() -> None:
    reg = _populated_registry()
    decision = process_click(
        session_id="s1",
        metadata={"suggestion_id": "sg_001"},
        registry=reg,
    )
    assert decision.kind == "unknown_label"


def test_evicted_old_suggestion_returns_stale() -> None:
    """When the deque overflows, old suggestions become stale."""
    reg = SuggestionRegistry(maxlen=2)
    reg.record(session_id="s1", suggestion_id="sg_old", options=[{"label": "a"}])
    reg.record(session_id="s1", suggestion_id="sg_mid", options=[{"label": "b"}])
    reg.record(session_id="s1", suggestion_id="sg_new", options=[{"label": "c"}])
    # sg_old should be evicted now
    decision = process_click(
        session_id="s1",
        metadata={"suggestion_id": "sg_old", "label": "a"},
        registry=reg,
    )
    assert decision.kind == "stale"
