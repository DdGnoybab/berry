"""Tests for build_approval_card / build_resolved_card."""

from __future__ import annotations

import json

from berry.channels.feishu.card_ux_approval import (
    BERRY_APPROVAL_CANCEL_ACTION,
    BERRY_APPROVAL_CONFIRM_ACTION,
    build_approval_card,
    build_resolved_card,
)
from berry.channels.feishu.card_interaction import BERRY_CARD_INTERACTION_VERSION


def test_approval_card_v1_orange_header() -> None:
    raw = build_approval_card(
        tool_name="bash",
        args={"command": "rm foo"},
        reason="contains 'rm '",
        approval_id="appr_x",
        expected_user_open_id="ou_a",
        expected_chat_id="oc_b",
        expires_at_ms=1730000000000,
    )
    card = json.loads(raw)
    # Schema v1 — no top-level "schema" key; uses wide_screen_mode + flat
    # top-level "elements".
    assert "schema" not in card
    assert card["config"]["wide_screen_mode"] is True
    assert card["header"]["template"] == "orange"
    assert card["header"]["title"]["content"] == "berry · 需要确认"


def test_approval_card_has_two_buttons_with_envelope_values() -> None:
    raw = build_approval_card(
        tool_name="bash", args={"command": "rm foo"}, reason=None,
        approval_id="appr_x",
        expected_user_open_id="ou_a", expected_chat_id="oc_b",
        expires_at_ms=1730000000000,
    )
    card = json.loads(raw)
    elements = card["elements"]
    action_block = next(e for e in elements if e["tag"] == "action")
    buttons = action_block["actions"]
    assert len(buttons) == 2

    confirm = buttons[0]
    cancel = buttons[1]
    assert confirm["text"]["content"] == "✅ 允许"
    assert confirm["type"] == "primary"
    assert confirm["value"]["a"] == BERRY_APPROVAL_CONFIRM_ACTION
    assert confirm["value"]["oc"] == BERRY_CARD_INTERACTION_VERSION
    assert confirm["value"]["m"] == {"approval_id": "appr_x"}
    assert confirm["value"]["c"] == {
        "u": "ou_a", "h": "oc_b", "e": 1730000000000,
    }

    assert cancel["text"]["content"] == "❌ 拒绝"
    assert cancel["type"] == "danger"
    assert cancel["value"]["a"] == BERRY_APPROVAL_CANCEL_ACTION


def test_approval_card_includes_reason_when_given() -> None:
    raw = build_approval_card(
        tool_name="bash", args={"command": "rm foo"},
        reason="contains 'rm '",
        approval_id="appr_x",
        expected_user_open_id="ou_a", expected_chat_id="oc_b",
        expires_at_ms=1,
    )
    card = json.loads(raw)
    body = card["elements"][0]["text"]["content"]
    assert "原因" in body
    assert "contains 'rm '" in body


def test_resolved_card_allowed_is_green() -> None:
    raw = build_resolved_card(
        tool_name="bash", args={"command": "ls"}, state="allowed",
    )
    card = json.loads(raw)
    assert card["header"]["template"] == "green"
    assert "已允许" in card["elements"][0]["text"]["content"]
    # No action block / buttons
    assert all(e["tag"] != "action" for e in card["elements"])


def test_resolved_card_denied_is_red() -> None:
    raw = build_resolved_card(tool_name="bash", args={}, state="denied")
    card = json.loads(raw)
    assert card["header"]["template"] == "red"
    assert "已拒绝" in card["elements"][0]["text"]["content"]


def test_resolved_card_timeout_is_red() -> None:
    raw = build_resolved_card(tool_name="bash", args={}, state="timeout")
    card = json.loads(raw)
    assert card["header"]["template"] == "red"
    assert "超时" in card["elements"][0]["text"]["content"]
