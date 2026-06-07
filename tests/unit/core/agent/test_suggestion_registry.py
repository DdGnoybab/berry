"""Tests for SuggestionRegistry."""

from __future__ import annotations

from berry.core.agent.suggestion_registry import SuggestionRegistry


def test_record_and_lookup_returns_options() -> None:
    reg = SuggestionRegistry()
    reg.record(
        session_id="s",
        suggestion_id="sg1",
        options=[{"label": "A"}, {"label": "B"}],
    )
    found = reg.lookup(session_id="s", suggestion_id="sg1")
    assert found == [{"label": "A"}, {"label": "B"}]


def test_lookup_unknown_returns_none() -> None:
    reg = SuggestionRegistry()
    assert reg.lookup(session_id="s", suggestion_id="missing") is None


def test_session_isolation() -> None:
    reg = SuggestionRegistry()
    reg.record(session_id="a", suggestion_id="sg", options=[{"label": "X"}])
    assert reg.lookup(session_id="b", suggestion_id="sg") is None


def test_evict_when_maxlen_exceeded() -> None:
    reg = SuggestionRegistry(maxlen=2)
    reg.record(session_id="s", suggestion_id="sg1", options=[{"label": "1"}])
    reg.record(session_id="s", suggestion_id="sg2", options=[{"label": "2"}])
    reg.record(session_id="s", suggestion_id="sg3", options=[{"label": "3"}])
    assert reg.lookup(session_id="s", suggestion_id="sg1") is None
    assert reg.lookup(session_id="s", suggestion_id="sg2") == [{"label": "2"}]
    assert reg.lookup(session_id="s", suggestion_id="sg3") == [{"label": "3"}]


def test_is_latest() -> None:
    reg = SuggestionRegistry()
    reg.record(session_id="s", suggestion_id="sg1", options=[])
    reg.record(session_id="s", suggestion_id="sg2", options=[])
    assert reg.is_latest(session_id="s", suggestion_id="sg2") is True
    assert reg.is_latest(session_id="s", suggestion_id="sg1") is False
    assert reg.is_latest(session_id="s", suggestion_id="missing") is False


def test_is_latest_empty_session() -> None:
    reg = SuggestionRegistry()
    assert reg.is_latest(session_id="s", suggestion_id="sg") is False
