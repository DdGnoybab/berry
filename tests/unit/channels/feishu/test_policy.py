"""Policy / conversation_id 测试 — 对应 openclaw `policy.test.ts` 简化版。"""

from __future__ import annotations

from berry.channels.feishu.conversation_id import (
    build_dm_conversation_id,
    build_for_event,
    build_group_conversation_id,
)
from berry.channels.feishu.policy import (
    admit,
    check_dm_admission,
    check_group_admission,
    check_group_mention_required,
)
from berry.channels.feishu.types import FeishuChatType, FeishuMessageEvent

# ---- 测试辅助 ---------------------------------------------------------------


def _dm_event(sender: str = "ou_alice", text: str = "hi") -> FeishuMessageEvent:
    return FeishuMessageEvent(
        account_id="A",
        message_id="om_1",
        chat_id="oc_p2p",
        chat_type=FeishuChatType.P2P,
        sender_open_id=sender,
        text=text,
    )


def _group_event(
    *,
    chat_id: str = "oc_room",
    sender: str = "ou_alice",
    text: str = "hi",
    mentioned: list[str] | None = None,
) -> FeishuMessageEvent:
    return FeishuMessageEvent(
        account_id="A",
        message_id="om_1",
        chat_id=chat_id,
        chat_type=FeishuChatType.GROUP,
        sender_open_id=sender,
        text=text,
        mentioned_open_ids=mentioned or [],
    )


# ---- DM:open 模式(默认,对齐 openclaw)------------------------------------


def test_dm_open_admits_anyone() -> None:
    assert check_dm_admission("ou_a", dm_policy="open", allowed_open_ids=[]) is True
    assert (
        check_dm_admission("ou_random", dm_policy="open", allowed_open_ids=["ou_x"])
        is True
    )


def test_dm_open_still_rejects_empty_sender() -> None:
    """Even in open mode, missing sender_open_id is rejected — defends against
    malformed events that slipped through parse."""
    assert check_dm_admission("", dm_policy="open", allowed_open_ids=[]) is False
    assert check_dm_admission("   ", dm_policy="open", allowed_open_ids=[]) is False


# ---- DM:allowlist 模式 -----------------------------------------------------


def test_dm_allowlist_admits_when_in_list() -> None:
    assert (
        check_dm_admission(
            "ou_a", dm_policy="allowlist", allowed_open_ids=["ou_a", "ou_b"],
        )
        is True
    )


def test_dm_allowlist_rejects_when_not_in_list() -> None:
    assert (
        check_dm_admission(
            "ou_x", dm_policy="allowlist", allowed_open_ids=["ou_a", "ou_b"],
        )
        is False
    )


def test_dm_allowlist_rejects_when_list_empty() -> None:
    assert (
        check_dm_admission("ou_a", dm_policy="allowlist", allowed_open_ids=[])
        is False
    ), "allowlist 模式 + 空列表 = 拒所有(对齐 openclaw)"


def test_dm_allowlist_rejects_empty_sender() -> None:
    assert (
        check_dm_admission(
            "", dm_policy="allowlist", allowed_open_ids=["ou_a"],
        )
        is False
    )


# ---- 群聊准入 check_group_admission ----------------------------------------


def test_group_admission_rejects_dm() -> None:
    assert check_group_admission(_dm_event(), group_allow_from=["oc_room"]) is False


def test_group_admission_rejects_when_allow_from_empty() -> None:
    assert check_group_admission(_group_event(), group_allow_from=[]) is False


def test_group_admission_rejects_when_chat_id_not_listed() -> None:
    assert (
        check_group_admission(_group_event(chat_id="oc_other"), group_allow_from=["oc_room"])
        is False
    )


def test_group_admission_admits_when_chat_id_listed() -> None:
    assert (
        check_group_admission(_group_event(chat_id="oc_room"), group_allow_from=["oc_room", "oc_x"])
        is True
    )


def test_group_admission_strips_whitespace_in_allow_from() -> None:
    """env CSV 解析后可能残留空白;set 化时要 strip 掉,不能因为 ' oc_room '
    而拒了 'oc_room'。"""
    assert (
        check_group_admission(
            _group_event(chat_id="oc_room"),
            group_allow_from=[" oc_room ", "", "  "],
        )
        is True
    )


# ---- 群聊唤醒 check_group_mention_required ---------------------------------


def test_mention_required_returns_true_when_disabled() -> None:
    """require_mention=False → 永远 True(预留接口)。"""
    ev = _group_event(mentioned=[])
    assert check_group_mention_required(
        ev, bot_open_id="ou_bot", require_mention=False,
    ) is True


def test_mention_required_returns_false_when_bot_open_id_missing() -> None:
    """启动期 bot_open_id 没解出来 → 群聊保守拒。"""
    ev = _group_event(mentioned=["ou_bot"])
    assert check_group_mention_required(ev, bot_open_id=None) is False
    assert check_group_mention_required(ev, bot_open_id="") is False


def test_mention_required_returns_false_when_bot_not_mentioned() -> None:
    ev = _group_event(mentioned=["ou_other"])
    assert check_group_mention_required(ev, bot_open_id="ou_bot") is False


def test_mention_required_returns_true_when_bot_mentioned() -> None:
    ev = _group_event(mentioned=["ou_bot", "ou_other"])
    assert check_group_mention_required(ev, bot_open_id="ou_bot") is True


# ---- admit 综合 ------------------------------------------------------------


def test_admit_dm_open_lets_through() -> None:
    assert admit(_dm_event(), dm_policy="open", allowed_open_ids=[]) is True


def test_admit_dm_allowlist_path() -> None:
    ev = _dm_event(sender="ou_alice")
    assert admit(ev, dm_policy="allowlist", allowed_open_ids=["ou_alice"]) is True
    assert admit(ev, dm_policy="allowlist", allowed_open_ids=["ou_other"]) is False


def test_admit_group_happy_path() -> None:
    ev = _group_event(chat_id="oc_room", mentioned=["ou_bot"])
    assert (
        admit(
            ev,
            dm_policy="open",
            allowed_open_ids=[],
            bot_open_id="ou_bot",
            group_allow_from=["oc_room"],
        )
        is True
    )


def test_admit_group_rejects_when_chat_not_listed() -> None:
    ev = _group_event(chat_id="oc_other", mentioned=["ou_bot"])
    assert (
        admit(
            ev,
            dm_policy="open",
            allowed_open_ids=[],
            bot_open_id="ou_bot",
            group_allow_from=["oc_room"],
        )
        is False
    )


def test_admit_group_rejects_when_not_mentioned() -> None:
    ev = _group_event(chat_id="oc_room", mentioned=[])
    assert (
        admit(
            ev,
            dm_policy="open",
            allowed_open_ids=[],
            bot_open_id="ou_bot",
            group_allow_from=["oc_room"],
        )
        is False
    )


def test_admit_group_rejects_when_bot_open_id_missing() -> None:
    """配了 group_allow_from 但 bot_open_id 缺 → 群聊整体拒。"""
    ev = _group_event(chat_id="oc_room", mentioned=["ou_bot"])
    assert (
        admit(
            ev,
            dm_policy="open",
            allowed_open_ids=[],
            bot_open_id=None,
            group_allow_from=["oc_room"],
        )
        is False
    )


def test_admit_group_rejects_when_group_allow_from_empty() -> None:
    """没配 group_allow_from → 群聊整体禁用。"""
    ev = _group_event(chat_id="oc_room", mentioned=["ou_bot"])
    assert (
        admit(
            ev,
            dm_policy="open",
            allowed_open_ids=[],
            bot_open_id="ou_bot",
            group_allow_from=[],
        )
        is False
    )


# ---- conversation_id -------------------------------------------------------


def test_dm_conversation_id_shape() -> None:
    assert build_dm_conversation_id("acct", "ou_xyz") == "feishu:acct:direct:ou_xyz"


def test_group_conversation_id_shape() -> None:
    assert (
        build_group_conversation_id("acct", "oc_xyz")
        == "feishu:acct:group:oc_xyz"
    )


def test_build_for_event_dm() -> None:
    assert build_for_event(_dm_event(sender="ou_alice")) == "feishu:A:direct:ou_alice"


def test_build_for_event_group() -> None:
    assert (
        build_for_event(_group_event(chat_id="oc_room"))
        == "feishu:A:group:oc_room"
    )
