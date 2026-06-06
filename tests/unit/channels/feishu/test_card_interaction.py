"""Tests for card_interaction envelope encode/decode + 4-way validation."""

from __future__ import annotations

from berry.channels.feishu.card_interaction import (
    BERRY_CARD_INTERACTION_VERSION,
    create_envelope,
    decode_action,
)


def test_create_envelope_minimal() -> None:
    env = create_envelope(action="berry.approval.confirm")
    assert env == {
        "oc": BERRY_CARD_INTERACTION_VERSION,
        "k": "button",
        "a": "berry.approval.confirm",
    }


def test_create_envelope_full() -> None:
    env = create_envelope(
        kind="button",
        action="berry.approval.confirm",
        metadata={"approval_id": "appr_x"},
        expected_user_open_id="ou_user",
        expected_chat_id="oc_chat",
        expires_at_ms=1730000000000,
    )
    assert env["m"] == {"approval_id": "appr_x"}
    assert env["c"] == {"u": "ou_user", "h": "oc_chat", "e": 1730000000000}


def test_decode_roundtrip_structured() -> None:
    env = create_envelope(
        action="berry.approval.confirm",
        metadata={"approval_id": "appr_x"},
        expected_user_open_id="ou_a",
        expected_chat_id="oc_b",
        expires_at_ms=2_000_000_000_000,
    )
    decoded = decode_action(
        action_value=env, operator_open_id="ou_a", chat_id="oc_b", now_ms=0,
    )
    assert decoded.kind == "structured"
    assert decoded.envelope == env


def test_decode_legacy_no_oc_is_malformed() -> None:
    decoded = decode_action(
        action_value={"foo": "bar"}, operator_open_id="ou", chat_id="oc",
    )
    assert decoded.kind == "invalid"
    assert decoded.reason == "malformed"


def test_decode_non_dict_action_value_is_malformed() -> None:
    decoded = decode_action(
        action_value="some-text", operator_open_id="ou", chat_id="oc",
    )
    assert decoded.kind == "invalid"
    assert decoded.reason == "malformed"


def test_decode_unknown_kind_is_malformed() -> None:
    env = {"oc": BERRY_CARD_INTERACTION_VERSION, "k": "weird", "a": "x"}
    decoded = decode_action(action_value=env, operator_open_id="ou", chat_id="oc")
    assert decoded.kind == "invalid"
    assert decoded.reason == "malformed"


def test_decode_empty_action_name_is_malformed() -> None:
    env = {"oc": BERRY_CARD_INTERACTION_VERSION, "k": "button", "a": ""}
    decoded = decode_action(action_value=env, operator_open_id="ou", chat_id="oc")
    assert decoded.kind == "invalid"
    assert decoded.reason == "malformed"


def test_decode_expired_is_stale() -> None:
    env = create_envelope(action="berry.approval.confirm", expires_at_ms=100)
    decoded = decode_action(
        action_value=env, operator_open_id="ou", chat_id="oc", now_ms=200,
    )
    assert decoded.kind == "invalid"
    assert decoded.reason == "stale"


def test_decode_wrong_user() -> None:
    env = create_envelope(action="x", expected_user_open_id="ou_a")
    decoded = decode_action(
        action_value=env, operator_open_id="ou_b", chat_id="oc", now_ms=0,
    )
    assert decoded.kind == "invalid"
    assert decoded.reason == "wrong_user"


def test_decode_wrong_conversation() -> None:
    env = create_envelope(action="x", expected_chat_id="oc_a")
    decoded = decode_action(
        action_value=env, operator_open_id="ou", chat_id="oc_b", now_ms=0,
    )
    assert decoded.kind == "invalid"
    assert decoded.reason == "wrong_conversation"


def test_decode_user_check_skipped_when_envelope_unset() -> None:
    """If envelope didn't pin operator, any operator is fine."""
    env = create_envelope(action="x")
    decoded = decode_action(
        action_value=env, operator_open_id="anyone", chat_id="oc", now_ms=0,
    )
    assert decoded.kind == "structured"


def test_decode_stale_takes_precedence_over_wrong_user() -> None:
    """Order matches openclaw: stale checked before user mismatch."""
    env = create_envelope(
        action="x", expected_user_open_id="ou_a", expires_at_ms=100,
    )
    decoded = decode_action(
        action_value=env, operator_open_id="ou_b", chat_id="oc", now_ms=200,
    )
    assert decoded.reason == "stale"
