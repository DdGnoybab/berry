"""Policy / conversation_id 测试 — 对应 openclaw `policy.test.ts` 简化版。"""

from __future__ import annotations

import pytest

from berry.channels.feishu.conversation_id import (
    build_dm_conversation_id,
    build_for_event,
)
from berry.channels.feishu.policy import admit, check_dm_admission
from berry.channels.feishu.types import FeishuChatType, FeishuMessageEvent


# ---- DM allowlist -----------------------------------------------------------


def test_dm_admit_when_in_allowlist() -> None:
    assert check_dm_admission("ou_a", ["ou_a", "ou_b"]) is True


def test_dm_reject_when_not_in_allowlist() -> None:
    assert check_dm_admission("ou_x", ["ou_a", "ou_b"]) is False


def test_dm_reject_when_allowlist_empty() -> None:
    assert check_dm_admission("ou_a", []) is False, "MVP 严格模式:空名单 = 拒所有"


def test_dm_reject_empty_sender() -> None:
    assert check_dm_admission("", ["ou_a"]) is False
    assert check_dm_admission("   ", ["ou_a"]) is False


# ---- 群聊 ------------------------------------------------------------------


def test_admit_rejects_group_in_mvp() -> None:
    ev = FeishuMessageEvent(
        account_id="acct",
        message_id="om_1",
        chat_id="oc_room",
        chat_type=FeishuChatType.GROUP,
        sender_open_id="ou_a",
        text="hi",
    )
    assert admit(ev, allowed_open_ids=["ou_a"]) is False, (
        "MVP 不响应群聊,即使 sender 在 DM allowlist"
    )


# ---- conversation_id -------------------------------------------------------


def test_dm_conversation_id_shape() -> None:
    assert build_dm_conversation_id("acct", "ou_xyz") == "feishu:acct:direct:ou_xyz"


def test_build_for_event_dm() -> None:
    ev = FeishuMessageEvent(
        account_id="A",
        message_id="om_1",
        chat_id="oc_p2p",
        chat_type=FeishuChatType.P2P,
        sender_open_id="ou_alice",
        text="hi",
    )
    assert build_for_event(ev) == "feishu:A:direct:ou_alice"


def test_build_for_event_group_raises() -> None:
    ev = FeishuMessageEvent(
        account_id="A",
        message_id="om_1",
        chat_id="oc_room",
        chat_type=FeishuChatType.GROUP,
        sender_open_id="ou_alice",
        text="hi",
    )
    with pytest.raises(NotImplementedError):
        build_for_event(ev)


def test_admit_dm_path() -> None:
    ev = FeishuMessageEvent(
        account_id="A",
        message_id="om_1",
        chat_id="oc_p2p",
        chat_type=FeishuChatType.P2P,
        sender_open_id="ou_alice",
        text="hi",
    )
    assert admit(ev, allowed_open_ids=["ou_alice"]) is True
    assert admit(ev, allowed_open_ids=["ou_other"]) is False
