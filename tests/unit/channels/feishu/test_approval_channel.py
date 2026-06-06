"""Unit tests for FeishuApprovalChannel.

These exercise:
- happy path: card sent → user click → resolved + card patched → ask returns True
- timeout: card sent → no click → ask returns False + timeout card patched
- no resolver: ask returns False without sending anything
- no chat (resolver returns None): ask returns False without sending anything
- send_approval_card failure: ask returns False, registry cleaned up

The lark client is faked in-process; the card_action handler runs synchronously
just like lark's dispatcher would invoke it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

import berry.channels.feishu.approval_channel as ach_mod
import berry.core.agent.approval_registry as reg_mod
from berry.channels.feishu.approval_channel import FeishuApprovalChannel
from berry.channels.feishu.card_action import handle_card_action
from berry.channels.feishu.card_action_dedupe import _reset_for_tests
from berry.channels.feishu.card_interaction import create_envelope
from berry.channels.feishu.card_ux_approval import (
    BERRY_APPROVAL_CANCEL_ACTION,
    BERRY_APPROVAL_CONFIRM_ACTION,
)
from berry.core.agent.approval_registry import get_approval_registry
from berry.core.tools.base import ToolContext


# ─── fake lark client ───────────────────────────────────────────────


class _CreateResp:
    code = 0
    msg = "ok"

    class _Data:
        message_id = "msg_xyz"

    data = _Data()

    def success(self) -> bool:
        return True


class _PatchResp:
    code = 0
    msg = "ok"

    def success(self) -> bool:
        return True


class _FailCreateResp:
    code = 1
    msg = "boom"
    data = None

    def success(self) -> bool:
        return False


class FakeMessage:
    def __init__(self) -> None:
        self.created: list[Any] = []
        self.patched: list[Any] = []
        self.fail_next_create = False

    def create(self, req: Any) -> Any:
        self.created.append(req)
        if self.fail_next_create:
            return _FailCreateResp()
        return _CreateResp()

    def patch(self, req: Any) -> Any:
        self.patched.append(req)
        return _PatchResp()


class FakeClient:
    def __init__(self) -> None:
        self.message = FakeMessage()
        self.im = type(
            "Im", (), {"v1": type("V1", (), {"message": self.message})()},
        )()


# ─── fixtures ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    reg_mod._global_registry = None
    _reset_for_tests()


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


def _ctx(session_id: str = "sess_a") -> ToolContext:
    return ToolContext(
        session_id=session_id,
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp"),
        cwd=Path("/tmp"),
    )


# ─── tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_returns_false_when_no_resolver(fake_client: FakeClient) -> None:
    channel = FeishuApprovalChannel(client=fake_client)  # type: ignore[arg-type]
    approved = await channel.ask("bash", {"command": "rm foo"}, _ctx())
    assert approved is False
    assert fake_client.message.created == []


@pytest.mark.asyncio
async def test_ask_returns_false_when_chat_unknown(fake_client: FakeClient) -> None:
    channel = FeishuApprovalChannel(client=fake_client)  # type: ignore[arg-type]
    channel.set_chat_resolver(lambda _sid: (None, None))
    approved = await channel.ask("bash", {"command": "rm foo"}, _ctx())
    assert approved is False
    assert fake_client.message.created == []


@pytest.mark.asyncio
async def test_ask_returns_false_when_send_fails(
    fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client.message.fail_next_create = True
    channel = FeishuApprovalChannel(client=fake_client)  # type: ignore[arg-type]
    channel.set_chat_resolver(lambda _sid: ("chat", "ou_user"))
    approved = await channel.ask("bash", {"command": "rm foo"}, _ctx())
    assert approved is False
    # Registry has no leaks (cleanup ran in finally)
    assert get_approval_registry()._pending == {}
    assert get_approval_registry()._metadata == {}


@pytest.mark.asyncio
async def test_ask_happy_path_resolves_via_card_action(
    fake_client: FakeClient,
) -> None:
    channel = FeishuApprovalChannel(client=fake_client)  # type: ignore[arg-type]
    channel.set_chat_resolver(lambda _sid: ("chat_x", "ou_user"))

    async def _click_confirm() -> None:
        # let ask register + send first
        await asyncio.sleep(0.02)
        reg = get_approval_registry()
        approval_id = next(iter(reg._pending.keys()))
        env = create_envelope(
            action=BERRY_APPROVAL_CONFIRM_ACTION,
            metadata={"approval_id": approval_id},
            expected_user_open_id="ou_user",
            expected_chat_id="chat_x",
            expires_at_ms=2_000_000_000_000,
        )
        raw_event = _make_card_action_event(
            operator_open_id="ou_user",
            token="tok_1",
            action_value=env,
            chat_id="chat_x",
            message_id="msg_xyz",
        )
        handle_card_action(fake_client, raw_event, account_id="acc")  # type: ignore[arg-type]

    task = asyncio.create_task(_click_confirm())
    approved = await channel.ask(
        "bash", {"command": "rm foo"}, _ctx(), reason="contains 'rm '",
    )
    await task

    assert approved is True
    assert len(fake_client.message.created) == 1   # approval card
    assert len(fake_client.message.patched) == 1   # → resolved card
    # Registry leak check
    assert get_approval_registry()._pending == {}
    assert get_approval_registry()._metadata == {}


@pytest.mark.asyncio
async def test_ask_cancel_returns_false(fake_client: FakeClient) -> None:
    channel = FeishuApprovalChannel(client=fake_client)  # type: ignore[arg-type]
    channel.set_chat_resolver(lambda _sid: ("chat_x", "ou_user"))

    async def _click_cancel() -> None:
        await asyncio.sleep(0.02)
        reg = get_approval_registry()
        aid = next(iter(reg._pending.keys()))
        env = create_envelope(
            action=BERRY_APPROVAL_CANCEL_ACTION,
            metadata={"approval_id": aid},
            expected_user_open_id="ou_user",
            expected_chat_id="chat_x",
            expires_at_ms=2_000_000_000_000,
        )
        handle_card_action(
            fake_client,  # type: ignore[arg-type]
            _make_card_action_event(
                operator_open_id="ou_user",
                token="tok_2",
                action_value=env,
                chat_id="chat_x",
                message_id="msg_xyz",
            ),
            account_id="acc",
        )

    task = asyncio.create_task(_click_cancel())
    approved = await channel.ask(
        "bash", {"command": "rm foo"}, _ctx(), reason="contains 'rm '",
    )
    await task
    assert approved is False
    assert len(fake_client.message.patched) == 1


@pytest.mark.asyncio
async def test_ask_timeout_patches_card(
    fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ach_mod, "APPROVAL_TIMEOUT_SECONDS", 0.05)
    channel = FeishuApprovalChannel(client=fake_client)  # type: ignore[arg-type]
    channel.set_chat_resolver(lambda _sid: ("chat_x", "ou_user"))

    approved = await channel.ask(
        "bash", {"command": "rm foo"}, _ctx(), reason="r",
    )
    assert approved is False
    assert len(fake_client.message.created) == 1
    # Timeout path patches the card to "timeout" state
    assert len(fake_client.message.patched) == 1


@pytest.mark.asyncio
async def test_wrong_user_click_does_not_resolve(
    fake_client: FakeClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ach_mod, "APPROVAL_TIMEOUT_SECONDS", 0.1)
    channel = FeishuApprovalChannel(client=fake_client)  # type: ignore[arg-type]
    channel.set_chat_resolver(lambda _sid: ("chat_x", "ou_legit"))

    async def _wrong_user() -> None:
        await asyncio.sleep(0.02)
        reg = get_approval_registry()
        aid = next(iter(reg._pending.keys()))
        env = create_envelope(
            action=BERRY_APPROVAL_CONFIRM_ACTION,
            metadata={"approval_id": aid},
            expected_user_open_id="ou_legit",
            expected_chat_id="chat_x",
            expires_at_ms=2_000_000_000_000,
        )
        handle_card_action(
            fake_client,  # type: ignore[arg-type]
            _make_card_action_event(
                operator_open_id="ou_attacker",
                token="tok_3",
                action_value=env,
                chat_id="chat_x",
                message_id="msg_xyz",
            ),
            account_id="acc",
        )

    task = asyncio.create_task(_wrong_user())
    approved = await channel.ask(
        "bash", {"command": "rm foo"}, _ctx(), reason="r",
    )
    await task
    # Wrong user does NOT resolve → eventually timeout → False
    assert approved is False
    # Notice + approval card created (2 creates total; notice is text, card is interactive)
    assert len(fake_client.message.created) == 2
    # Patch only happened from the timeout path
    assert len(fake_client.message.patched) == 1


# ─── helper ─────────────────────────────────────────────────────────


def _make_card_action_event(
    *,
    operator_open_id: str,
    token: str,
    action_value: dict[str, Any],
    chat_id: str,
    message_id: str,
) -> Any:
    """Synthesize a P2CardActionTrigger-shaped object."""

    class _Operator:
        def __init__(self) -> None:
            self.open_id = operator_open_id

    class _Action:
        def __init__(self) -> None:
            self.value = action_value
            self.tag = "button"

    class _Context:
        def __init__(self) -> None:
            self.open_message_id = message_id
            self.chat_id = chat_id

    class _Event:
        def __init__(self) -> None:
            self.operator = _Operator()
            self.token = token
            self.action = _Action()
            self.context = _Context()

    class _Raw:
        def __init__(self) -> None:
            self.event = _Event()

    return _Raw()
