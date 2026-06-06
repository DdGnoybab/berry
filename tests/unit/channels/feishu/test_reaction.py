"""reaction.py 测试 — add_typing_reaction / remove_reaction 的正确性和容错。

mock lark Client,不真调飞书 API。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from berry.channels.feishu.reaction import (
    TYPING_EMOJI,
    add_typing_reaction,
    remove_reaction,
)


class _OkCreateResp:
    code = 0
    msg = "ok"

    class _Data:
        reaction_id = "re_abc123"

    data = _Data()

    def success(self) -> bool:
        return True


class _FailResp:
    code = 99991663
    msg = "no permission"
    data = None

    def success(self) -> bool:
        return False


class _FakeReactionApi:
    def __init__(self) -> None:
        self.created: list[Any] = []
        self.deleted: list[Any] = []
        self.fail = False

    def create(self, req: Any) -> Any:
        self.created.append(req)
        return _FailResp() if self.fail else _OkCreateResp()

    def delete(self, req: Any) -> Any:
        self.deleted.append(req)
        return _FailResp() if self.fail else _OkCreateResp()


def _make_client(reaction_api: _FakeReactionApi) -> MagicMock:
    client = MagicMock()
    client.im.v1.message_reaction = reaction_api
    return client


# ---- add_typing_reaction ----


class TestAddTypingReaction:
    def test_success_returns_reaction_id(self) -> None:
        api = _FakeReactionApi()
        client = _make_client(api)
        rid = add_typing_reaction(client, "om_msg1")
        assert rid == "re_abc123"
        assert len(api.created) == 1

    def test_api_failure_returns_none(self) -> None:
        api = _FakeReactionApi()
        api.fail = True
        client = _make_client(api)
        rid = add_typing_reaction(client, "om_msg1")
        assert rid is None

    def test_exception_returns_none(self) -> None:
        client = MagicMock()
        client.im.v1.message_reaction.create.side_effect = RuntimeError("network")
        rid = add_typing_reaction(client, "om_msg1")
        assert rid is None

    def test_emoji_type_is_typing(self) -> None:
        api = _FakeReactionApi()
        client = _make_client(api)
        add_typing_reaction(client, "om_msg1")
        req = api.created[0]
        body = req.request_body
        assert body.reaction_type.emoji_type == TYPING_EMOJI == "Typing"

    def test_message_id_passed_correctly(self) -> None:
        api = _FakeReactionApi()
        client = _make_client(api)
        add_typing_reaction(client, "om_test_id")
        req = api.created[0]
        assert req.message_id == "om_test_id"


# ---- remove_reaction ----


class TestRemoveReaction:
    def test_success(self) -> None:
        api = _FakeReactionApi()
        client = _make_client(api)
        remove_reaction(client, "om_msg1", "re_abc")
        assert len(api.deleted) == 1

    def test_api_failure_does_not_raise(self) -> None:
        api = _FakeReactionApi()
        api.fail = True
        client = _make_client(api)
        remove_reaction(client, "om_msg1", "re_abc")  # should not raise

    def test_exception_does_not_raise(self) -> None:
        client = MagicMock()
        client.im.v1.message_reaction.delete.side_effect = RuntimeError("boom")
        remove_reaction(client, "om_msg1", "re_abc")  # should not raise

    def test_ids_passed_correctly(self) -> None:
        api = _FakeReactionApi()
        client = _make_client(api)
        remove_reaction(client, "om_msg2", "re_xyz")
        req = api.deleted[0]
        assert req.message_id == "om_msg2"
        assert req.reaction_id == "re_xyz"
