"""bot.parse_feishu_message_event 测试 — 把 SDK 事件 dict 喂给 lark 类后
归一化是否正确。"""

from __future__ import annotations

import json

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from berry.channels.feishu.bot import parse_feishu_message_event
from berry.channels.feishu.types import FeishuChatType


def _make_raw(*, msg_id: str, chat_id: str, chat_type: str, sender_open_id: str,
              msg_type: str = "text", content: str | None = None,
              mentions: list[dict] | None = None) -> P2ImMessageReceiveV1:
    return P2ImMessageReceiveV1(
        d={
            "schema": "2.0",
            "header": {"event_type": "im.message.receive_v1", "token": "x"},
            "event": {
                "sender": {
                    "sender_id": {"open_id": sender_open_id},
                    "sender_type": "user",
                },
                "message": {
                    "message_id": msg_id,
                    "chat_id": chat_id,
                    "chat_type": chat_type,
                    "message_type": msg_type,
                    "content": content if content is not None else json.dumps({"text": "hi"}),
                    "create_time": "1717000000000",
                    "mentions": mentions or [],
                },
            },
        }
    )


def test_parse_dm_text_event() -> None:
    raw = _make_raw(
        msg_id="om_1",
        chat_id="oc_p2p",
        chat_type="p2p",
        sender_open_id="ou_alice",
        content=json.dumps({"text": "hello berry"}),
    )

    ev = parse_feishu_message_event("acct1", raw)
    assert ev is not None
    assert ev.account_id == "acct1"
    assert ev.message_id == "om_1"
    assert ev.chat_id == "oc_p2p"
    assert ev.chat_type == FeishuChatType.P2P
    assert ev.sender_open_id == "ou_alice"
    assert ev.text == "hello berry"
    assert ev.create_time_ms == 1717000000000


def test_parse_strips_mention_placeholders() -> None:
    raw = _make_raw(
        msg_id="om_2",
        chat_id="oc_room",
        chat_type="group",
        sender_open_id="ou_alice",
        content=json.dumps({"text": "@_user_1 yo"}),
        mentions=[
            {
                "key": "@_user_1",
                "id": {"open_id": "ou_bot"},
                "name": "berry",
                "tenant_key": "t",
            }
        ],
    )
    ev = parse_feishu_message_event("acct1", raw)
    assert ev is not None
    assert ev.text == "yo"
    assert "ou_bot" in ev.mentioned_open_ids


def test_parse_returns_none_for_missing_message_id() -> None:
    raw = _make_raw(
        msg_id="",
        chat_id="oc_p2p",
        chat_type="p2p",
        sender_open_id="ou_alice",
    )
    assert parse_feishu_message_event("acct1", raw) is None


def test_parse_returns_none_for_missing_sender_open_id() -> None:
    raw = _make_raw(
        msg_id="om_1",
        chat_id="oc_p2p",
        chat_type="p2p",
        sender_open_id="",
    )
    assert parse_feishu_message_event("acct1", raw) is None


def test_parse_returns_none_for_unknown_chat_type() -> None:
    raw = _make_raw(
        msg_id="om_1",
        chat_id="oc_x",
        chat_type="weird",
        sender_open_id="ou_alice",
    )
    assert parse_feishu_message_event("acct1", raw) is None


def test_parse_image_msg_type_returns_empty_text() -> None:
    raw = _make_raw(
        msg_id="om_3",
        chat_id="oc_p2p",
        chat_type="p2p",
        sender_open_id="ou_alice",
        msg_type="image",
        content=json.dumps({"image_key": "img_xxx"}),
    )
    ev = parse_feishu_message_event("acct1", raw)
    assert ev is not None
    assert ev.text == ""
