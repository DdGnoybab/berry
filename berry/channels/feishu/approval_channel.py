"""FeishuApprovalChannel — implements ``ApprovalChannel`` over Feishu cards.

Send an approval card on ``ask``, await ``ApprovalRegistry`` future for the
user click; ``card_action.handle_card_action`` resolves the future when the
button is pressed.

``chat_resolver`` is post-injected by ``entrypoints/feishu.py`` to break a
construction cycle (channel needs adapter to know which chat to send to,
adapter needs runner to wire the runtime, runtime needs the channel).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import lark_oapi as lark

from berry.channels.feishu.card_ux_approval import (
    build_approval_card,
    build_resolved_card,
)
from berry.channels.feishu.send import (
    send_approval_card,
    update_card_by_message,
)
from berry.core.agent.approval_registry import get_approval_registry
from berry.core.tools.base import ToolContext
from berry.observability.logging import get_logger

logger = get_logger(__name__)

ChatResolver = Callable[[str], tuple[str | None, str | None]]
"""``session_id -> (chat_id, expected_user_open_id)``.

Returns ``(None, None)`` when the session has no Feishu chat context (e.g.
a session that was created via the CLI). Channel falls back to deny when
that happens — never blocks the turn.
"""

APPROVAL_TIMEOUT_SECONDS = 90.0


class FeishuApprovalChannel:
    """ApprovalChannel backed by Feishu interactive cards (single-message
    approval, NOT streaming card embed — see spec §3 method B)."""

    def __init__(self, *, client: lark.Client) -> None:
        self._client = client
        self._chat_resolver: ChatResolver | None = None

    def set_chat_resolver(self, resolver: ChatResolver) -> None:
        self._chat_resolver = resolver

    async def ask(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
        reason: str | None = None,
    ) -> bool:
        if self._chat_resolver is None:
            logger.error("feishu_approval_no_resolver", session_id=ctx.session_id)
            return False

        chat_id, expected_open_id = self._chat_resolver(ctx.session_id)
        if chat_id is None:
            logger.error("feishu_approval_no_chat", session_id=ctx.session_id)
            return False

        registry = get_approval_registry()
        approval_id, _future = registry.register()
        registry.attach_metadata(
            approval_id, {"tool_name": tool_name, "args": args},
        )

        try:
            expires_at_ms = int((time.time() + APPROVAL_TIMEOUT_SECONDS) * 1000)
            card_json = build_approval_card(
                tool_name=tool_name,
                args=args,
                reason=reason,
                approval_id=approval_id,
                expected_user_open_id=expected_open_id,
                expected_chat_id=chat_id,
                expires_at_ms=expires_at_ms,
            )
            message_id = send_approval_card(
                self._client, chat_id=chat_id, card_json=card_json,
            )
            if message_id is None:
                logger.error(
                    "feishu_approval_card_send_failed",
                    approval_id=approval_id,
                    chat_id=chat_id,
                )
                return False

            registry.attach_metadata(approval_id, {"message_id": message_id})
            logger.info(
                "feishu_approval_card_sent",
                approval_id=approval_id,
                chat_id=chat_id,
                message_id=message_id,
            )

            verdict = await registry.wait(
                approval_id, timeout_seconds=APPROVAL_TIMEOUT_SECONDS,
            )

            if verdict.reason == "approval timeout":
                # Handler had no chance to update the card; flip it to "timeout"
                # so the user doesn't see a stale orange-pending card forever.
                update_card_by_message(
                    self._client,
                    message_id=message_id,
                    card_json=build_resolved_card(
                        tool_name=tool_name, args=args, state="timeout",
                    ),
                )
            return verdict.approved
        finally:
            registry.cleanup(approval_id)
