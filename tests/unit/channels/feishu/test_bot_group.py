"""bot.handle_feishu_message 群聊路径测试。

覆盖:
- 群准入失败 → 不调 runtime / 不出站
- 群 happy path:运行 LLM、给文本加 sender 前缀、出站走 reply
- LLM 抛异常 → 错误兜底文本仍 reply 到原消息
- 卡片发送失败 → 兜底纯文本也走 reply
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import berry.channels.feishu.bot as bot_mod
import berry.channels.feishu.runtime as runtime_mod
from berry.channels.feishu.runtime_adapter import FeishuRuntimeAdapter
from berry.channels.feishu.types import FeishuChatType, FeishuMessageEvent


def _group_event(
    *,
    chat_id: str = "oc_room",
    sender: str = "ou_alice",
    text: str = "hello berry",
    mentioned: list[str] | None = None,
    message_id: str = "om_trigger",
) -> FeishuMessageEvent:
    return FeishuMessageEvent(
        account_id="A",
        message_id=message_id,
        chat_id=chat_id,
        chat_type=FeishuChatType.GROUP,
        sender_open_id=sender,
        text=text,
        mentioned_open_ids=mentioned or ["ou_bot"],
    )


@pytest.fixture(autouse=True)
def _reset_runtime() -> None:
    runtime_mod.clear_feishu_runtime()


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mock FeishuRuntimeAdapter,透出 run_turn 调用记录。"""
    adapter = MagicMock(spec=FeishuRuntimeAdapter)

    async def _run_turn(*args: Any, **kwargs: Any) -> str:
        return "berry: ok"

    adapter.run_turn.side_effect = _run_turn
    runtime_mod.set_feishu_runtime(adapter)
    return adapter


@pytest.fixture
def captured_send(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """拦截 send_card_markdown / send_text,记录调用参数。"""
    calls: dict[str, list[Any]] = {"card": [], "text": []}

    def _fake_card(client: Any, **kwargs: Any) -> bool:
        calls["card"].append(kwargs)
        return True

    def _fake_text(client: Any, **kwargs: Any) -> bool:
        calls["text"].append(kwargs)
        return True

    monkeypatch.setattr(bot_mod.send_mod, "send_card_markdown", _fake_card)
    monkeypatch.setattr(bot_mod.send_mod, "send_text", _fake_text)
    monkeypatch.setattr(
        bot_mod, "get_http_client", lambda _aid: MagicMock(name="lark_client"),
    )
    return calls


# ---- 准入路径 --------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_blocked_when_chat_not_in_allow_from(
    fake_adapter: MagicMock, captured_send: dict[str, list[Any]],
) -> None:
    ev = _group_event(chat_id="oc_other")
    await bot_mod.handle_feishu_message(
        ev,
        dm_policy="open",
        allowed_open_ids=[],
        bot_open_id="ou_bot",
        group_allow_from=["oc_room"],
    )
    assert fake_adapter.run_turn.called is False
    assert captured_send["card"] == []
    assert captured_send["text"] == []


@pytest.mark.asyncio
async def test_group_blocked_when_bot_not_mentioned(
    fake_adapter: MagicMock, captured_send: dict[str, list[Any]],
) -> None:
    ev = _group_event(mentioned=["ou_someone_else"])
    await bot_mod.handle_feishu_message(
        ev,
        dm_policy="open",
        allowed_open_ids=[],
        bot_open_id="ou_bot",
        group_allow_from=["oc_room"],
    )
    assert fake_adapter.run_turn.called is False
    assert captured_send["card"] == []


@pytest.mark.asyncio
async def test_group_blocked_when_bot_open_id_missing(
    fake_adapter: MagicMock, captured_send: dict[str, list[Any]],
) -> None:
    ev = _group_event(mentioned=["ou_bot"])
    await bot_mod.handle_feishu_message(
        ev,
        dm_policy="open",
        allowed_open_ids=[],
        bot_open_id=None,
        group_allow_from=["oc_room"],
    )
    assert fake_adapter.run_turn.called is False


# ---- happy path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_happy_path_runs_turn_and_replies(
    fake_adapter: MagicMock, captured_send: dict[str, list[Any]],
) -> None:
    ev = _group_event(
        chat_id="oc_room",
        sender="ou_alice",
        text="hello berry",
        mentioned=["ou_bot"],
        message_id="om_trigger_1",
    )
    await bot_mod.handle_feishu_message(
        ev,
        dm_policy="open",
        allowed_open_ids=[],
        bot_open_id="ou_bot",
        group_allow_from=["oc_room"],
    )

    # run_turn 被调一次,user_text 带 sender 前缀
    assert fake_adapter.run_turn.call_count == 1
    args, kwargs = fake_adapter.run_turn.call_args
    assert args[0] == "feishu:A:group:oc_room"
    assert args[1] == "[sender:ou_alice] hello berry"
    assert kwargs == {
        "chat_id": "oc_room",
        "user_open_id": "ou_alice",
        "trigger_message_id": "om_trigger_1",
    }

    # 出站走 reply 到 trigger 消息
    assert len(captured_send["card"]) == 1
    card_kwargs = captured_send["card"][0]
    assert card_kwargs["chat_id"] == "oc_room"
    assert card_kwargs["markdown"] == "berry: ok"
    assert card_kwargs["reply_to_message_id"] == "om_trigger_1"
    assert captured_send["text"] == []


@pytest.mark.asyncio
async def test_group_runtime_exception_falls_back_to_error_text(
    fake_adapter: MagicMock, captured_send: dict[str, list[Any]],
) -> None:
    async def _boom(*_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("LLM exploded")

    fake_adapter.run_turn.side_effect = _boom

    ev = _group_event(message_id="om_x")
    await bot_mod.handle_feishu_message(
        ev,
        dm_policy="open",
        allowed_open_ids=[],
        bot_open_id="ou_bot",
        group_allow_from=["oc_room"],
    )
    assert len(captured_send["card"]) == 1
    msg = captured_send["card"][0]["markdown"]
    assert "RuntimeError" in msg
    assert captured_send["card"][0]["reply_to_message_id"] == "om_x"


@pytest.mark.asyncio
async def test_group_card_failure_falls_back_to_text_reply(
    fake_adapter: MagicMock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """卡片发送失败 → 兜底纯文本,且也走 reply。"""
    text_calls: list[Any] = []

    def _bad_card(client: Any, **kwargs: Any) -> bool:
        return False

    def _ok_text(client: Any, **kwargs: Any) -> bool:
        text_calls.append(kwargs)
        return True

    monkeypatch.setattr(bot_mod.send_mod, "send_card_markdown", _bad_card)
    monkeypatch.setattr(bot_mod.send_mod, "send_text", _ok_text)
    monkeypatch.setattr(
        bot_mod, "get_http_client", lambda _aid: MagicMock(),
    )

    ev = _group_event(message_id="om_xx")
    await bot_mod.handle_feishu_message(
        ev,
        dm_policy="open",
        allowed_open_ids=[],
        bot_open_id="ou_bot",
        group_allow_from=["oc_room"],
    )
    assert len(text_calls) == 1
    assert text_calls[0]["reply_to_message_id"] == "om_xx"


# ---- DM 不受群聊改动影响 --------------------------------------------------


@pytest.mark.asyncio
async def test_dm_path_does_not_use_reply_or_sender_prefix(
    fake_adapter: MagicMock, captured_send: dict[str, list[Any]],
) -> None:
    ev = FeishuMessageEvent(
        account_id="A",
        message_id="om_dm",
        chat_id="oc_p2p",
        chat_type=FeishuChatType.P2P,
        sender_open_id="ou_alice",
        text="hi berry",
    )
    await bot_mod.handle_feishu_message(
        ev,
        dm_policy="open",
        allowed_open_ids=[],
        bot_open_id="ou_bot",
        group_allow_from=["oc_room"],
    )

    args, _ = fake_adapter.run_turn.call_args
    # DM 不加 sender 前缀
    assert args[1] == "hi berry"
    # DM 出站不 reply
    assert captured_send["card"][0]["reply_to_message_id"] is None
