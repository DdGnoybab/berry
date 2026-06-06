"""Tests for ProgressWatcher: emit SuggestEmittedEvent when progress.json
.current.last_suggestion has a new produced_at, never twice for the same one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from berry.assistants.learning.progress_watcher import (
    ProgressWatcher,
    SuggestEmittedEvent,
    get_default_watcher,
    reset_default_watcher_for_testing,
)


def _write_progress(workspace: Path, payload: dict[str, object]) -> None:
    berry_dir = workspace / ".berry"
    berry_dir.mkdir(parents=True, exist_ok=True)
    (berry_dir / "progress.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _suggestion(produced_at: str) -> dict[str, object]:
    return {
        "produced_at": produced_at,
        "context": "post_assess",
        "score": 5.0,
        "weak_points": ["x"],
        "options": [{"key": "teach_full", "label": "完整重讲", "recommended": True}],
        "sub_menu": None,
    }


def test_emits_event_for_new_suggestion(tmp_path: Path) -> None:
    _write_progress(
        tmp_path,
        {
            "topic": "redis",
            "current": {"atom": "a3", "last_suggestion": _suggestion("2026-06-06T18:25:00")},
        },
    )
    watcher = ProgressWatcher()
    captured: list[SuggestEmittedEvent] = []
    watcher.register_listener(captured.append)

    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)

    assert len(captured) == 1
    ev = captured[0]
    assert ev.conversation_id == "conv1"
    assert ev.topic == "redis"
    assert ev.atom == "a3"
    assert ev.suggestion["produced_at"] == "2026-06-06T18:25:00"


def test_does_not_re_emit_when_produced_at_unchanged(tmp_path: Path) -> None:
    _write_progress(
        tmp_path,
        {"current": {"last_suggestion": _suggestion("2026-06-06T18:25:00")}},
    )
    watcher = ProgressWatcher()
    captured: list[SuggestEmittedEvent] = []
    watcher.register_listener(captured.append)

    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)
    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)
    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)

    assert len(captured) == 1


def test_emits_again_when_produced_at_changes(tmp_path: Path) -> None:
    watcher = ProgressWatcher()
    captured: list[SuggestEmittedEvent] = []
    watcher.register_listener(captured.append)

    _write_progress(
        tmp_path,
        {"current": {"last_suggestion": _suggestion("2026-06-06T18:25:00")}},
    )
    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)
    assert len(captured) == 1

    _write_progress(
        tmp_path,
        {"current": {"last_suggestion": _suggestion("2026-06-06T18:30:00")}},
    )
    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)
    assert len(captured) == 2
    assert captured[1].suggestion["produced_at"] == "2026-06-06T18:30:00"


def test_per_conversation_cache_independent(tmp_path: Path) -> None:
    """Two workspaces, two conversations — they don't see each other's state."""
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    _write_progress(
        ws_a, {"current": {"last_suggestion": _suggestion("2026-06-06T18:25:00")}}
    )
    _write_progress(
        ws_b, {"current": {"last_suggestion": _suggestion("2026-06-06T18:25:00")}}
    )

    watcher = ProgressWatcher()
    captured: list[SuggestEmittedEvent] = []
    watcher.register_listener(captured.append)

    watcher.reconcile(conversation_id="conv_a", workspace_path=ws_a)
    watcher.reconcile(conversation_id="conv_b", workspace_path=ws_b)

    assert len(captured) == 2
    convs = {ev.conversation_id for ev in captured}
    assert convs == {"conv_a", "conv_b"}


def test_missing_progress_file_silent(tmp_path: Path) -> None:
    watcher = ProgressWatcher()
    captured: list[SuggestEmittedEvent] = []
    watcher.register_listener(captured.append)

    # No .berry/progress.json at all
    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)

    assert captured == []


def test_malformed_progress_file_silent(tmp_path: Path) -> None:
    berry_dir = tmp_path / ".berry"
    berry_dir.mkdir()
    (berry_dir / "progress.json").write_text("{not valid json", encoding="utf-8")

    watcher = ProgressWatcher()
    captured: list[SuggestEmittedEvent] = []
    watcher.register_listener(captured.append)

    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)

    assert captured == []


def test_no_suggestion_field_silent(tmp_path: Path) -> None:
    _write_progress(
        tmp_path,
        {"topic": "redis", "current": {"atom": "a3", "last_suggestion": None}},
    )
    watcher = ProgressWatcher()
    captured: list[SuggestEmittedEvent] = []
    watcher.register_listener(captured.append)

    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)

    assert captured == []


def test_listener_exception_does_not_crash_reconcile(tmp_path: Path) -> None:
    _write_progress(
        tmp_path,
        {"current": {"last_suggestion": _suggestion("2026-06-06T18:25:00")}},
    )
    watcher = ProgressWatcher()

    def boom(_event: SuggestEmittedEvent) -> None:
        raise RuntimeError("listener bug")

    captures: list[SuggestEmittedEvent] = []
    watcher.register_listener(boom)
    watcher.register_listener(captures.append)

    # Should not raise
    watcher.reconcile(conversation_id="conv1", workspace_path=tmp_path)

    # The good listener still fired
    assert len(captures) == 1


def test_default_watcher_is_singleton() -> None:
    reset_default_watcher_for_testing()
    a = get_default_watcher()
    b = get_default_watcher()
    assert a is b
    reset_default_watcher_for_testing()
    c = get_default_watcher()
    assert c is not a


@pytest.fixture(autouse=True)
def _reset_default_watcher() -> None:
    reset_default_watcher_for_testing()
