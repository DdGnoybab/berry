"""Tests for the simplified Feishu SUGGEST card builder.

After ADR-0010 the card takes ``{prompt, options}`` only — no score /
weak_points / sub_menu / atom_label / context.
"""

from __future__ import annotations

import json

from berry.channels.feishu.card_interaction import BERRY_CARD_INTERACTION_VERSION
from berry.channels.feishu.cards.suggest_card import (
    LEARNING_PICK_OPTION_ACTION,
    build_suggest_card,
    build_suggest_card_resolved,
)


def _basic_options() -> list[dict[str, object]]:
    return [
        {"label": "完整重讲", "recommended": True},
        {"label": "只补漏点"},
        {"label": "我懂了"},
        {"label": "跳过"},
    ]


def test_card_blue_header_v2_schema() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_001",
        prompt="你想怎么继续?",
        options=_basic_options(),
    )
    card = json.loads(raw)
    assert card["schema"] == "2.0"
    assert card["header"]["template"] == "blue"


def test_prompt_appears_in_body() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_001",
        prompt="你想怎么继续?",
        options=_basic_options(),
    )
    card = json.loads(raw)
    body_md = card["body"]["elements"][0]["content"]
    assert "你想怎么继续?" in body_md


def test_recommended_option_starred_and_primary() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_001",
        prompt="?",
        options=_basic_options(),
    )
    card = json.loads(raw)
    rows = [el for el in card["body"]["elements"] if el.get("tag") == "action"]
    first_btn = rows[0]["actions"][0]
    assert first_btn["text"]["content"].startswith("⭐ ")
    assert first_btn["type"] == "primary"
    second_btn = rows[0]["actions"][1]
    assert not second_btn["text"]["content"].startswith("⭐")
    assert second_btn["type"] == "default"


def test_envelope_carries_suggestion_id_and_label() -> None:
    raw = build_suggest_card(
        suggestion_id="sg_xyz",
        prompt="?",
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
    assert env["m"]["label"] == "完整重讲"
    assert env["c"]["u"] == "ou_a"
    assert env["c"]["h"] == "oc_b"


def test_descriptions_render_inline() -> None:
    options = [
        {"label": "全力以赴", "description": "彻底学一遍"},
        {"label": "随便看看"},
    ]
    raw = build_suggest_card(suggestion_id="sg_x", prompt="?", options=options)
    card = json.loads(raw)
    body_md = card["body"]["elements"][0]["content"]
    assert "彻底学一遍" in body_md


def test_resolved_card_grey_header_no_buttons() -> None:
    raw = build_suggest_card_resolved(chosen_label="完整重讲", was_recommended=True)
    card = json.loads(raw)
    assert card["header"]["template"] == "grey"
    assert all(el.get("tag") != "action" for el in card["body"]["elements"])
    body_md = card["body"]["elements"][0]["content"]
    assert "已选择" in body_md
    assert "完整重讲" in body_md
    assert "⭐" in body_md


def test_buttons_chunk_into_rows_of_4() -> None:
    options = [{"label": f"选项{i}"} for i in range(8)]
    raw = build_suggest_card(suggestion_id="sg_x", prompt="?", options=options)
    card = json.loads(raw)
    rows = [el for el in card["body"]["elements"] if el.get("tag") == "action"]
    assert len(rows) == 2
    assert len(rows[0]["actions"]) == 4
    assert len(rows[1]["actions"]) == 4
