"""send.py 测试 — DM 走 create / 群聊走 reply 的分支正确性。

核心校验:``reply_to_message_id`` 决定走哪个 lark API。
不真发飞书,只 mock 客户端的 create / reply / patch 入口。
"""

from __future__ import annotations

from typing import Any

import pytest

from berry.channels.feishu.send import (
    send_approval_card,
    send_card_markdown,
    send_invalid_notice,
    send_text,
)


class _OkResp:
    code = 0
    msg = "ok"

    class _Data:
        message_id = "om_returned"

    data = _Data()

    def success(self) -> bool:
        return True


class _FailResp:
    code = 1
    msg = "boom"
    data = None

    def success(self) -> bool:
        return False


class _FakeMessageApi:
    def __init__(self) -> None:
        self.created: list[Any] = []
        self.replied: list[Any] = []
        self.patched: list[Any] = []
        self.fail = False

    def create(self, req: Any) -> Any:
        self.created.append(req)
        return _FailResp() if self.fail else _OkResp()

    def reply(self, req: Any) -> Any:
        self.replied.append(req)
        return _FailResp() if self.fail else _OkResp()

    def patch(self, req: Any) -> Any:
        self.patched.append(req)
        return _OkResp()


class _FakeClient:
    def __init__(self) -> None:
        self.message = _FakeMessageApi()
        self.im = type(
            "Im", (), {"v1": type("V1", (), {"message": self.message})()},
        )()


@pytest.fixture
def client() -> _FakeClient:
    return _FakeClient()


# ---- send_text -------------------------------------------------------------


def test_send_text_uses_create_when_no_reply_to(client: _FakeClient) -> None:
    ok = send_text(client, chat_id="oc_a", text="hello")  # type: ignore[arg-type]
    assert ok is True
    assert len(client.message.created) == 1
    assert len(client.message.replied) == 0


def test_send_text_uses_reply_when_reply_to_given(client: _FakeClient) -> None:
    ok = send_text(
        client, chat_id="oc_a", text="hello", reply_to_message_id="om_x",  # type: ignore[arg-type]
    )
    assert ok is True
    assert len(client.message.replied) == 1
    assert len(client.message.created) == 0


def test_send_text_returns_false_on_api_error(client: _FakeClient) -> None:
    client.message.fail = True
    ok = send_text(client, chat_id="oc_a", text="hello")  # type: ignore[arg-type]
    assert ok is False


# ---- send_card_markdown ----------------------------------------------------


def test_send_card_markdown_uses_create_when_no_reply_to(
    client: _FakeClient,
) -> None:
    ok = send_card_markdown(client, chat_id="oc_a", markdown="# yo")  # type: ignore[arg-type]
    assert ok is True
    assert len(client.message.created) == 1
    assert len(client.message.replied) == 0


def test_send_card_markdown_uses_reply_when_reply_to_given(
    client: _FakeClient,
) -> None:
    ok = send_card_markdown(
        client, chat_id="oc_a", markdown="# yo", reply_to_message_id="om_x",  # type: ignore[arg-type]
    )
    assert ok is True
    assert len(client.message.replied) == 1
    assert len(client.message.created) == 0


# ---- send_approval_card ----------------------------------------------------


def test_send_approval_card_uses_create_when_no_reply_to(
    client: _FakeClient,
) -> None:
    msg_id = send_approval_card(client, chat_id="oc_a", card_json="{}")  # type: ignore[arg-type]
    assert msg_id == "om_returned"
    assert len(client.message.created) == 1
    assert len(client.message.replied) == 0


def test_send_approval_card_uses_reply_when_reply_to_given(
    client: _FakeClient,
) -> None:
    msg_id = send_approval_card(
        client, chat_id="oc_a", card_json="{}", reply_to_message_id="om_x",  # type: ignore[arg-type]
    )
    assert msg_id == "om_returned"
    assert len(client.message.replied) == 1
    assert len(client.message.created) == 0


def test_send_approval_card_returns_none_on_api_error(
    client: _FakeClient,
) -> None:
    client.message.fail = True
    msg_id = send_approval_card(
        client, chat_id="oc_a", card_json="{}", reply_to_message_id="om_x",  # type: ignore[arg-type]
    )
    assert msg_id is None


# ---- send_invalid_notice ---------------------------------------------------


def test_send_invalid_notice_passes_reply_to_through(client: _FakeClient) -> None:
    ok = send_invalid_notice(
        client, chat_id="oc_a", reason="malformed", reply_to_message_id="om_x",  # type: ignore[arg-type]
    )
    assert ok is True
    assert len(client.message.replied) == 1


def test_send_invalid_notice_create_when_no_reply_to(client: _FakeClient) -> None:
    ok = send_invalid_notice(client, chat_id="oc_a", reason="malformed")  # type: ignore[arg-type]
    assert ok is True
    assert len(client.message.created) == 1
