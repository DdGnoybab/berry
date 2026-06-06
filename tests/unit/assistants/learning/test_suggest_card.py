"""Tests for the SUGGEST card builder."""

from __future__ import annotations

import json

from berry.assistants.learning.cards.suggest_card import (
    LEARNING_PICK_OPTION_ACTION,
    LEARNING_PICK_SUB_OPTION_ACTION,
    build_suggest_card,
    build_suggest_card_resolved,
)
from berry.channels.feishu.card_interaction import BERRY_CARD_INTERACTION_VERSION


def _basic_options() -> list[dict[str, object]]:
    return [
        {"key": "teach_full", "label": "完整重讲", "recommended": True},
        {"key": "teach_lite", "label": "只补漏点"},
        {"key": "teach_restyle", "label": "换种方式讲", "expands_to": "restyle_modes"},
        {"key": "teach_deeper", "label": "深入讲", "expands_to": "deeper_directions"},
        {"key": "more_q", "label": "再来一题"},
        {"key": "change_q_set", "label": "换组题"},
        {"key": "self_done", "label": "我懂了标 done"},
        {"key": "skip_atom", "label": "跳过这个 atom"},
    ]


def test_suggest_card_blue_header_and_v2_schema() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_001",
        atom_label="a3 quicklist",
        context="post_assess",
        score=5.0,
        weak_points=["quicklist 节点编码"],
        options=_basic_options(),
        user_open_id="ou_a",
        chat_id="oc_b",
    )
    card = json.loads(raw)
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"
    assert "berry-L" in card["header"]["title"]["content"]
    assert "a3 quicklist" in card["header"]["title"]["content"]


def test_suggest_card_score_and_weak_points_in_body() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_001",
        atom_label="a3 quicklist",
        context="post_assess",
        score=5.0,
        weak_points=["quicklist 节点编码", "为什么不用 linkedlist"],
        options=_basic_options(),
    )
    card = json.loads(raw)
    body_md = card["body"]["elements"][0]["content"]
    assert "5.0" in body_md
    assert "quicklist 节点编码" in body_md
    assert "为什么不用 linkedlist" in body_md


def test_suggest_card_recommended_option_marked_with_star_and_primary() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_001",
        atom_label="a3",
        context="post_assess",
        score=5.0,
        weak_points=[],
        options=_basic_options(),
    )
    card = json.loads(raw)
    # Find the first action element and inspect its first button
    action_elements = [el for el in card["body"]["elements"] if el.get("tag") == "action"]
    assert action_elements, "should have at least one action row"
    first_btn = action_elements[0]["actions"][0]
    assert first_btn["text"]["content"].startswith("⭐ ")
    assert first_btn["type"] == "primary"
    # Non-recommended buttons should be default style
    second_btn = action_elements[0]["actions"][1]
    assert not second_btn["text"]["content"].startswith("⭐")
    assert second_btn["type"] == "default"


def test_suggest_card_buttons_chunk_into_rows_of_4() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_001",
        atom_label="a3",
        context="post_assess",
        score=5.0,
        weak_points=[],
        options=_basic_options(),  # 8 options
    )
    card = json.loads(raw)
    action_rows = [el for el in card["body"]["elements"] if el.get("tag") == "action"]
    # 8 options → 2 rows of 4
    assert len(action_rows) == 2
    assert len(action_rows[0]["actions"]) == 4
    assert len(action_rows[1]["actions"]) == 4


def test_suggest_card_button_envelope_carries_suggestion_id_and_key() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_xyz",
        atom_label="a3",
        context="post_assess",
        score=5.0,
        weak_points=[],
        options=_basic_options(),
        user_open_id="ou_a",
        chat_id="oc_b",
        expires_at_ms=1_730_000_000_000,
    )
    card = json.loads(raw)
    first_btn = next(
        a
        for el in card["body"]["elements"]
        if el.get("tag") == "action"
        for a in el["actions"]
    )
    env = first_btn["value"]
    assert env["oc"] == BERRY_CARD_INTERACTION_VERSION
    assert env["a"] == LEARNING_PICK_OPTION_ACTION
    assert env["m"]["suggestion_id"] == "sg_xyz"
    assert env["m"]["key"] == "teach_full"
    assert env["c"]["u"] == "ou_a"
    assert env["c"]["h"] == "oc_b"
    assert env["c"]["e"] == 1_730_000_000_000


def test_suggest_card_strong_recommended_uses_double_star() -> None:
    options = [
        {"key": "skip_atom", "label": "跳过这个 atom", "strong_recommended": True},
        {"key": "teach_full", "label": "完整重讲"},
    ]
    raw = build_suggest_card(
        suggestion_id="sg_x",
        atom_label="a3",
        context="post_assess",
        score=2.0,
        weak_points=["反复卡壳"],
        options=options,
    )
    card = json.loads(raw)
    first_btn = next(
        a
        for el in card["body"]["elements"]
        if el.get("tag") == "action"
        for a in el["actions"]
    )
    assert first_btn["text"]["content"].startswith("⭐⭐ ")
    assert first_btn["type"] == "primary"


def test_suggest_card_post_probe_no_score_omits_score_line() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_x",
        atom_label="a1",
        context="post_teach",
        score=None,
        weak_points=[],
        options=[
            {"key": "assess", "label": "测一下", "recommended": True},
            {"key": "next_atom", "label": "进下个 atom"},
        ],
    )
    card = json.loads(raw)
    body_md = card["body"]["elements"][0]["content"]
    assert "得分" not in body_md
    assert "我建议" in body_md
    assert "测一下" in body_md


def test_suggest_card_with_sub_menu_renders_restyle_options_and_sub_action() -> None:
    sub_menu = {
        "parent_choice": "teach_restyle",
        "parent_label": "换种方式讲",
        "prompt": "你想我换什么方式?",
        "options": [
            {"key": "vivid", "label": "更形象"},
            {"key": "precise", "label": "更精准"},
            {"key": "by_code", "label": "用代码讲"},
            {"key": "from_problem", "label": "从问题反推"},
            {"key": "shorter", "label": "更短"},
        ],
    }
    raw = build_suggest_card(
        suggestion_id="sg_x",
        atom_label="a3",
        context="post_assess",
        score=5.0,
        weak_points=["编码切换"],
        options=_basic_options(),
        sub_menu=sub_menu,
    )
    card = json.loads(raw)
    # Title shows we're in a sub-menu
    title = card["header"]["title"]["content"]
    assert "↘" in title
    assert "换种方式讲" in title
    # Sub buttons use the SUB action, not the main action
    action_rows = [el for el in card["body"]["elements"] if el.get("tag") == "action"]
    btns = [a for row in action_rows for a in row["actions"]]
    assert len(btns) == 5
    for btn in btns:
        assert btn["value"]["a"] == LEARNING_PICK_SUB_OPTION_ACTION
    keys = [btn["value"]["m"]["key"] for btn in btns]
    assert keys == ["vivid", "precise", "by_code", "from_problem", "shorter"]


def test_suggest_card_resolved_grey_header_no_buttons() -> None:
    raw = build_suggest_card_resolved(
        atom_label="a3 quicklist",
        context="post_assess",
        chosen_label="完整重讲",
        was_recommended=True,
    )
    card = json.loads(raw)
    assert card["header"]["template"] == "grey"
    assert card["schema"] == "2.0"
    # No action elements
    assert all(el.get("tag") != "action" for el in card["body"]["elements"])
    body_md = card["body"]["elements"][0]["content"]
    assert "你选了" in body_md
    assert "完整重讲" in body_md
    assert "⭐" in body_md  # was_recommended → star prefix


def test_suggest_card_extra_note_appears_when_provided() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_x",
        atom_label="a3",
        context="post_assess",
        score=2.0,
        weak_points=["反复卡壳"],
        options=[
            {"key": "skip_atom", "label": "跳过", "strong_recommended": True},
            {"key": "teach_full", "label": "再讲一遍"},
        ],
        extra_note="这是第 3 次了 — 强烈建议先跳过,等相关 atom 学完回来再看。",
    )
    card = json.loads(raw)
    body_md = card["body"]["elements"][0]["content"]
    assert "第 3 次" in body_md
