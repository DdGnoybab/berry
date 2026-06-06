"""Tests for click_handler.process_click — pure logic, no SDK."""

from __future__ import annotations

import json
from pathlib import Path

from berry.assistants.learning.cards.suggest_card import (
    LEARNING_PICK_OPTION_ACTION,
    LEARNING_PICK_SUB_OPTION_ACTION,
)
from berry.assistants.learning.click_handler import process_click


def _write_progress(workspace: Path, last_suggestion: dict[str, object]) -> None:
    berry_dir = workspace / ".berry"
    berry_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "topic": "redis",
        "current": {
            "atom": "a3",
            "last_suggestion": last_suggestion,
        },
    }
    (berry_dir / "progress.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _suggestion(
    *,
    suggestion_id: str = "sg_001",
    options: list[dict[str, object]] | None = None,
    sub_menu: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "suggestion_id": suggestion_id,
        "produced_at": "2026-06-06T18:25:00",
        "context": "post_assess",
        "score": 5.0,
        "weak_points": ["x"],
        "options": options
        or [
            {"key": "teach_full", "label": "完整重讲", "recommended": True},
            {"key": "teach_restyle", "label": "换种方式讲", "expands_to": "restyle_modes"},
            {"key": "self_done", "label": "我懂了"},
        ],
        "sub_menu": sub_menu,
    }


def test_pick_option_synthesizes_user_message_with_label(tmp_path: Path) -> None:
    _write_progress(tmp_path, _suggestion())
    decision = process_click(
        action_name=LEARNING_PICK_OPTION_ACTION,
        metadata={"suggestion_id": "sg_001", "key": "teach_full"},
        workspace_path=tmp_path,
    )
    assert decision.kind == "pick_option"
    assert decision.chosen_key == "teach_full"
    assert decision.chosen_label == "完整重讲"
    assert decision.was_recommended is True
    assert decision.expands_to is None
    assert decision.synthesized_user_message == "完整重讲"


def test_pick_option_with_expands_to_returns_no_synth_message(tmp_path: Path) -> None:
    _write_progress(tmp_path, _suggestion())
    decision = process_click(
        action_name=LEARNING_PICK_OPTION_ACTION,
        metadata={"suggestion_id": "sg_001", "key": "teach_restyle"},
        workspace_path=tmp_path,
    )
    assert decision.kind == "pick_option"
    assert decision.chosen_key == "teach_restyle"
    assert decision.expands_to == "restyle_modes"
    # No synthesized turn — channel just renders the sub-menu in same card
    assert decision.synthesized_user_message is None


def test_pick_sub_option_combines_parent_and_choice(tmp_path: Path) -> None:
    sub = {
        "parent_choice": "teach_restyle",
        "parent_label": "换种方式讲",
        "options": [
            {"key": "vivid", "label": "更形象"},
            {"key": "by_code", "label": "用代码讲"},
        ],
    }
    _write_progress(tmp_path, _suggestion(sub_menu=sub))
    decision = process_click(
        action_name=LEARNING_PICK_SUB_OPTION_ACTION,
        metadata={"suggestion_id": "sg_001", "key": "vivid"},
        workspace_path=tmp_path,
    )
    assert decision.kind == "pick_sub_option"
    assert decision.chosen_key == "vivid"
    assert decision.chosen_label == "更形象"
    assert decision.synthesized_user_message == "换种方式讲 → 更形象"


def test_stale_click_when_suggestion_id_does_not_match(tmp_path: Path) -> None:
    """User clicks an old card after LLM has produced a new SUGGEST."""
    _write_progress(tmp_path, _suggestion(suggestion_id="sg_002"))
    decision = process_click(
        action_name=LEARNING_PICK_OPTION_ACTION,
        metadata={"suggestion_id": "sg_001", "key": "teach_full"},
        workspace_path=tmp_path,
    )
    assert decision.kind == "stale"


def test_unknown_key_in_main_options(tmp_path: Path) -> None:
    _write_progress(tmp_path, _suggestion())
    decision = process_click(
        action_name=LEARNING_PICK_OPTION_ACTION,
        metadata={"suggestion_id": "sg_001", "key": "made_up_key"},
        workspace_path=tmp_path,
    )
    assert decision.kind == "unknown_key"


def test_unknown_key_in_sub_options(tmp_path: Path) -> None:
    sub = {
        "parent_choice": "teach_restyle",
        "options": [{"key": "vivid", "label": "更形象"}],
    }
    _write_progress(tmp_path, _suggestion(sub_menu=sub))
    decision = process_click(
        action_name=LEARNING_PICK_SUB_OPTION_ACTION,
        metadata={"suggestion_id": "sg_001", "key": "made_up_sub"},
        workspace_path=tmp_path,
    )
    assert decision.kind == "unknown_key"


def test_missing_progress_file(tmp_path: Path) -> None:
    decision = process_click(
        action_name=LEARNING_PICK_OPTION_ACTION,
        metadata={"suggestion_id": "sg_001", "key": "x"},
        workspace_path=tmp_path,
    )
    assert decision.kind == "missing_progress"


def test_unknown_action_name(tmp_path: Path) -> None:
    _write_progress(tmp_path, _suggestion())
    decision = process_click(
        action_name="berry.something.else",
        metadata={"suggestion_id": "sg_001", "key": "teach_full"},
        workspace_path=tmp_path,
    )
    assert decision.kind == "unknown_key"


def test_strong_recommended_counts_as_recommended(tmp_path: Path) -> None:
    options = [
        {"key": "skip_atom", "label": "跳过", "strong_recommended": True},
        {"key": "teach_full", "label": "再讲一遍"},
    ]
    _write_progress(tmp_path, _suggestion(options=options))
    decision = process_click(
        action_name=LEARNING_PICK_OPTION_ACTION,
        metadata={"suggestion_id": "sg_001", "key": "skip_atom"},
        workspace_path=tmp_path,
    )
    assert decision.was_recommended is True


def test_no_suggestion_id_in_metadata_does_not_block_pick(tmp_path: Path) -> None:
    """Older clients / first roll-out: metadata may lack suggestion_id."""
    _write_progress(tmp_path, _suggestion())
    decision = process_click(
        action_name=LEARNING_PICK_OPTION_ACTION,
        metadata={"key": "teach_full"},
        workspace_path=tmp_path,
    )
    # Without suggestion_id we can't detect stale; we accept the pick
    assert decision.kind == "pick_option"
    assert decision.chosen_key == "teach_full"
