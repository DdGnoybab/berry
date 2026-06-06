"""Approval card schemas — pending state (with buttons) + resolved state.

Mirrors openclaw ``extensions/feishu/src/card-ux-approval.ts``:

- pending card uses an orange ``header.template`` to signal "needs attention"
- resolved card uses green/red to signal final state, removes buttons so the
  user cannot click again
- card uses Feishu CardKit v2 ``schema: "2.0"`` (matches openclaw)
- buttons carry a ``card_interaction`` envelope as ``value`` so the
  ``card.action.trigger`` handler can decode + validate operator/chat/expiry

Berry-specific: ``metadata.approval_id`` indexes ``ApprovalRegistry``.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from berry.channels.feishu.card_interaction import create_envelope
from berry.channels.feishu.card_ux_shared import build_button

BERRY_APPROVAL_CONFIRM_ACTION = "berry.approval.confirm"
BERRY_APPROVAL_CANCEL_ACTION = "berry.approval.cancel"

ResolvedState = Literal["allowed", "denied", "timeout"]


def build_approval_card(
    *,
    tool_name: str,
    args: dict[str, Any],
    reason: str | None,
    approval_id: str,
    expected_user_open_id: str | None,
    expected_chat_id: str | None,
    expires_at_ms: int,
) -> str:
    """Build the pending-approval card content (Feishu interactive JSON).

    Returns a JSON string ready to be sent as ``msg_type=interactive`` content.
    """
    args_compact = json.dumps(args, ensure_ascii=False, indent=2)
    reason_line = f"**原因**:{reason}\n\n" if reason else ""
    body_md = (
        "⚠️ **berry 想执行需要确认的操作**\n\n"
        f"{reason_line}"
        f"**工具**:`{tool_name}`\n"
        f"**参数**:\n```json\n{args_compact}\n```"
    )
    metadata = {"approval_id": approval_id}
    confirm_value = create_envelope(
        kind="button",
        action=BERRY_APPROVAL_CONFIRM_ACTION,
        metadata=metadata,
        expected_user_open_id=expected_user_open_id,
        expected_chat_id=expected_chat_id,
        expires_at_ms=expires_at_ms,
    )
    cancel_value = create_envelope(
        kind="button",
        action=BERRY_APPROVAL_CANCEL_ACTION,
        metadata=metadata,
        expected_user_open_id=expected_user_open_id,
        expected_chat_id=expected_chat_id,
        expires_at_ms=expires_at_ms,
    )
    # CardKit V2 schema — body.elements holds markdown + action buttons.
    card: dict[str, Any] = {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "berry · 需要确认"},
            "template": "orange",
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": body_md},
                {
                    "tag": "action",
                    "actions": [
                        build_button(label="✅ 允许", value=confirm_value, style="primary"),
                        build_button(label="❌ 拒绝", value=cancel_value, style="danger"),
                    ],
                },
            ],
        },
    }
    return json.dumps(card, ensure_ascii=False)


def build_resolved_card(
    *,
    tool_name: str,
    args: dict[str, Any],
    state: ResolvedState,
) -> str:
    """Build the immutable post-decision card (no buttons)."""
    state_label = {
        "allowed": "✅ 已允许",
        "denied": "❌ 已拒绝",
        "timeout": "⏱️ 超时(按拒绝处理)",
    }[state]
    template = "green" if state == "allowed" else "red"
    args_compact = json.dumps(args, ensure_ascii=False, indent=2)
    body_md = (
        f"{state_label}\n\n"
        f"**工具**:`{tool_name}`\n"
        f"**参数**:\n```json\n{args_compact}\n```"
    )
    card: dict[str, Any] = {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": "berry · 确认结果"},
            "template": template,
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": body_md},
            ],
        },
    }
    return json.dumps(card, ensure_ascii=False)
