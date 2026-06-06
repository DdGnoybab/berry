"""Integration: card.action.trigger event reaches the registry / patches card.

Goal: prove the event-shape contract between lark dispatcher and our
``handle_card_action`` is right, and that a malformed envelope does NOT
resolve the future. Uses a fake lark client; no network.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import berry.core.agent.approval_registry as reg_mod
from berry.channels.feishu.card_action import handle_card_action
from berry.channels.feishu.card_action_dedupe import _reset_for_tests
from berry.channels.feishu.card_interaction import create_envelope
from berry.channels.feishu.card_ux_approval import (
    BERRY_APPROVAL_CONFIRM_ACTION,
)
from berry.core.agent.approval_registry import get_approval_registry


# ─── shared fakes ───────────────────────────────────────────────────


class _Resp:
    code = 0
    msg = "ok"

    def success(self) -> bool:
        return True

    class _Data:
        message_id = "msg_x"

    data = _Data()


class _PatchResp:
    code = 0
    msg = "ok"

    def success(self) -> bool:
        return True


class FakeMessage:
    def __init__(self) -> None:
        self.created: list[Any] = []
        self.patched: list[Any] = []

    def create(self, req: Any) -> Any:
        self.created.append(req)
        return _Resp()

    def patch(self, req: Any) -> Any:
        self.patched.append(req)
        return _PatchResp()


class FakeClient:
    def __init__(self) -> None:
        self.message = FakeMessage()
        self.im = type(
            "Im", (), {"v1": type("V1", (), {"message": self.message})()},
        )()


def _event(*, operator_open_id: str, token: str, action_value: Any,
           chat_id: str, message_id: str) -> Any:
    """Synthesize a P2CardActionTrigger-shaped object. Built from instances
    rather than class-scope reads so we don't trip ``name = name`` rebinding
    (Python class bodies don't see enclosing-fn closures the way nested
    functions do)."""
    operator = type("O", (), {"open_id": operator_open_id})()
    action = type("A", (), {"value": action_value, "tag": "button"})()
    context = type("C", (), {"open_message_id": message_id, "chat_id": chat_id})()
    event = type("E", (), {
        "operator": operator,
        "token": token,
        "action": action,
        "context": context,
    })()
    return type("R", (), {"event": event})()


@pytest.fixture(autouse=True)
def _reset() -> None:
    reg_mod._global_registry = None
    _reset_for_tests()


# ─── tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_callback_resolves_and_patches() -> None:
    client = FakeClient()
    reg = get_approval_registry()
    approval_id, fut = reg.register()
    reg.attach_metadata(
        approval_id,
        {"tool_name": "bash", "args": {"command": "rm foo"}, "message_id": "msg_x"},
    )

    env = create_envelope(
        action=BERRY_APPROVAL_CONFIRM_ACTION,
        metadata={"approval_id": approval_id},
        expected_user_open_id="ou_a",
        expected_chat_id="chat_x",
        expires_at_ms=2_000_000_000_000,
    )
    handle_card_action(
        client,  # type: ignore[arg-type]
        _event(operator_open_id="ou_a", token="t1", action_value=env,
               chat_id="chat_x", message_id="msg_x"),
        account_id="acc",
    )

    # Future is now resolved
    assert fut.done()
    decision = fut.result()
    assert decision.approved is True

    # Card was patched once with the resolved schema
    assert len(client.message.patched) == 1


@pytest.mark.asyncio
async def test_wrong_user_does_not_resolve() -> None:
    client = FakeClient()
    reg = get_approval_registry()
    approval_id, fut = reg.register()
    reg.attach_metadata(approval_id, {"message_id": "msg_x"})

    env = create_envelope(
        action=BERRY_APPROVAL_CONFIRM_ACTION,
        metadata={"approval_id": approval_id},
        expected_user_open_id="ou_a",
        expected_chat_id="chat_x",
        expires_at_ms=2_000_000_000_000,
    )
    handle_card_action(
        client,  # type: ignore[arg-type]
        _event(operator_open_id="ou_other", token="t1", action_value=env,
               chat_id="chat_x", message_id="msg_x"),
        account_id="acc",
    )

    # Future stays pending; notice text was sent
    assert not fut.done()
    assert len(client.message.created) == 1
    # No patch on the original card
    assert len(client.message.patched) == 0


@pytest.mark.asyncio
async def test_duplicate_token_is_dedup_eaten() -> None:
    client = FakeClient()
    reg = get_approval_registry()
    approval_id, fut = reg.register()
    reg.attach_metadata(approval_id, {"message_id": "msg_x"})

    env = create_envelope(
        action=BERRY_APPROVAL_CONFIRM_ACTION,
        metadata={"approval_id": approval_id},
        expected_user_open_id="ou_a",
        expected_chat_id="chat_x",
        expires_at_ms=2_000_000_000_000,
    )
    ev = _event(operator_open_id="ou_a", token="dup_token", action_value=env,
                chat_id="chat_x", message_id="msg_x")

    handle_card_action(client, ev, account_id="acc")  # type: ignore[arg-type]
    assert fut.done()
    patches_after_first = len(client.message.patched)

    # Second delivery of the same token: ignored
    handle_card_action(client, ev, account_id="acc")  # type: ignore[arg-type]
    assert len(client.message.patched) == patches_after_first


@pytest.mark.asyncio
async def test_stale_envelope_does_not_resolve() -> None:
    client = FakeClient()
    reg = get_approval_registry()
    approval_id, fut = reg.register()

    env = create_envelope(
        action=BERRY_APPROVAL_CONFIRM_ACTION,
        metadata={"approval_id": approval_id},
        expires_at_ms=1,   # already past
    )
    handle_card_action(
        client,  # type: ignore[arg-type]
        _event(operator_open_id="ou_a", token="t1", action_value=env,
               chat_id="chat_x", message_id="msg_x"),
        account_id="acc",
    )
    assert not fut.done()
    # User got a stale notice (text msg)
    assert len(client.message.created) == 1
