"""Card button.value envelope encoder + 4-way validation decoder.

Mirrors openclaw ``extensions/feishu/src/card-interaction.ts``: berry uses
the same envelope shape and validation reasons (``malformed`` / ``stale`` /
``wrong_user`` / ``wrong_conversation``) so card_action handlers can render
matching error notices.

Berry-specific differences from openclaw:
- version prefix is ``"berry1"`` (openclaw uses ``"ocf1"``) so a card cannot
  be misinterpreted across products
- the metadata field ``m.approval_id`` is berry-only — it's the index that
  ``ApprovalRegistry`` uses to match the click back to a Future

Envelope shape::

    {
      "oc": "berry1",
      "k":  "button" | "quick",          # interaction kind
      "a":  "berry.approval.confirm",    # action name
      "m":  { "approval_id": "appr_..." },   # metadata (optional)
      "c":  {                                 # context (optional)
        "u": "ou_xxx",                        # expected operator open_id
        "h": "oc_xxx",                        # expected chat_id
        "e": 1730000000000,                   # expires_at (ms epoch)
      }
    }
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

BERRY_CARD_INTERACTION_VERSION = "berry1"

InteractionKind = Literal["button", "quick"]
DecodedReason = Literal["malformed", "stale", "wrong_user", "wrong_conversation"]


@dataclass(frozen=True)
class DecodedAction:
    """Result of ``decode_action``.

    - ``kind == "structured"`` → ``envelope`` is the validated dict
    - ``kind == "invalid"``    → ``reason`` describes which check failed
    """

    kind: Literal["structured", "invalid"]
    envelope: dict[str, Any] | None = None
    reason: DecodedReason | None = None


def create_envelope(
    *,
    kind: InteractionKind = "button",
    action: str,
    metadata: dict[str, Any] | None = None,
    expected_user_open_id: str | None = None,
    expected_chat_id: str | None = None,
    expires_at_ms: int | None = None,
) -> dict[str, Any]:
    """Build the dict that goes into a Feishu card button's ``value`` field."""
    env: dict[str, Any] = {
        "oc": BERRY_CARD_INTERACTION_VERSION,
        "k": kind,
        "a": action,
    }
    if metadata:
        env["m"] = dict(metadata)
    ctx: dict[str, Any] = {}
    if expected_user_open_id:
        ctx["u"] = expected_user_open_id
    if expected_chat_id:
        ctx["h"] = expected_chat_id
    if expires_at_ms is not None:
        ctx["e"] = expires_at_ms
    if ctx:
        env["c"] = ctx
    return env


def decode_action(
    *,
    action_value: Any,
    operator_open_id: str | None,
    chat_id: str | None,
    now_ms: int | None = None,
) -> DecodedAction:
    """Validate the envelope contained in ``card.action.trigger`` event.

    Validation order matches openclaw:
        1. version prefix present and matches BERRY_CARD_INTERACTION_VERSION
        2. ``k`` is a known kind, ``a`` is a non-empty string
        3. context ``c`` (if present) is a dict; ``e`` < now → stale;
           ``u`` mismatch → wrong_user; ``h`` mismatch → wrong_conversation
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)

    if not isinstance(action_value, dict):
        return DecodedAction(kind="invalid", reason="malformed")
    if action_value.get("oc") != BERRY_CARD_INTERACTION_VERSION:
        return DecodedAction(kind="invalid", reason="malformed")

    if action_value.get("k") not in ("button", "quick"):
        return DecodedAction(kind="invalid", reason="malformed")
    a = action_value.get("a")
    if not isinstance(a, str) or not a:
        return DecodedAction(kind="invalid", reason="malformed")

    ctx = action_value.get("c")
    if ctx is not None:
        if not isinstance(ctx, dict):
            return DecodedAction(kind="invalid", reason="malformed")
        e = ctx.get("e")
        if e is not None:
            if not isinstance(e, (int, float)):
                return DecodedAction(kind="invalid", reason="malformed")
            if e < now_ms:
                return DecodedAction(kind="invalid", reason="stale")
        u = ctx.get("u")
        if u:
            if not isinstance(u, str):
                return DecodedAction(kind="invalid", reason="malformed")
            if u.strip() != (operator_open_id or "").strip():
                return DecodedAction(kind="invalid", reason="wrong_user")
        h = ctx.get("h")
        if h:
            if not isinstance(h, str):
                return DecodedAction(kind="invalid", reason="malformed")
            if h.strip() != (chat_id or "").strip():
                return DecodedAction(kind="invalid", reason="wrong_conversation")

    return DecodedAction(kind="structured", envelope=action_value)
