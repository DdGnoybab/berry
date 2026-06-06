"""``card.action.trigger`` event handler.

Mirrors openclaw ``extensions/feishu/src/card-action.ts`` (single-purpose
slice for berry's approval flow):

1. Validate token (non-empty + dedupe via ``card_action_dedupe``)
2. Decode envelope + run 4-way validation (``decode_action``); on failure
   send a plain-text notice and DO NOT resolve the future — the original
   ``ApprovalChannel.ask`` keeps waiting until the legitimate user clicks
   or the 90s timeout fires.
3. On valid confirm/cancel: resolve ``ApprovalRegistry`` future with the
   user's decision.
4. Update the card to immutable allowed/denied state — but only when the
   resolve actually succeeded; if the future was already cleaned up
   (timeout race), we leave the card alone so the channel-side timeout
   patch wins.
"""

from __future__ import annotations

from typing import Any

import lark_oapi as lark

import json as _json

from lark_oapi.event.callback.model.p2_card_action_trigger import (
    CallBackCard,
    CallBackToast,
    P2CardActionTriggerResponse,
)

from berry.channels.feishu.card_action_dedupe import (
    begin_token,
    complete_token,
    release_token,
)
from berry.channels.feishu.card_interaction import decode_action
from berry.channels.feishu.card_ux_approval import (
    BERRY_APPROVAL_CANCEL_ACTION,
    BERRY_APPROVAL_CONFIRM_ACTION,
    build_resolved_card,
)
from berry.channels.feishu.send import send_invalid_notice, update_card_by_message
from berry.core.agent.approval_registry import (
    ApprovalAlreadyResolvedError,
    ApprovalNotFoundError,
    get_approval_registry,
)
from berry.observability.logging import get_logger

logger = get_logger(__name__)


# message_id → last resolved card JSON
# Feishu's callback protocol: the response's `card` field is authoritative —
# whatever we return overwrites the card UI. If we return an empty response
# on a duplicate-delivery (Feishu retries), Feishu reverts to the original
# unresolved card, "flickering" past the resolved state. Cache the last
# resolved card here so duplicate deliveries return the same authoritative
# card and don't undo the resolution.
_resolved_card_cache: dict[str, str] = {}
_RESOLVED_CARD_CACHE_MAX = 1024


def _remember_resolved_card(message_id: str, card_json: str) -> None:
    if len(_resolved_card_cache) >= _RESOLVED_CARD_CACHE_MAX:
        # crude FIFO eviction (single-process, low-volume use)
        _resolved_card_cache.pop(next(iter(_resolved_card_cache)), None)
    _resolved_card_cache[message_id] = card_json


def _recall_resolved_card(message_id: str | None) -> str | None:
    if not message_id:
        return None
    return _resolved_card_cache.get(message_id)


def _empty_response() -> P2CardActionTriggerResponse:
    """An "ack only, no card mutation" response.

    Used for early-exit paths (malformed envelope, dedup hit, etc.) where
    we don't want the click to change the card. lark's
    ``P2CardActionTriggerProcessor`` requires this exact return type;
    returning ``None`` makes the SDK synthesize a broken response.
    """
    return P2CardActionTriggerResponse({})


def _card_response(card_json: str) -> P2CardActionTriggerResponse:
    """Return a callback response that REPLACES the card body with
    ``card_json``.

    Why we need this: Feishu uses the callback's response card as the
    authoritative post-click state. If the response doesn't carry a card,
    Feishu reverts the message to its pre-click rendering, undoing any
    ``im.message.patch`` we did.

    Schema per Feishu docs (`card-callback-communication`):

        {"card": {"type": "raw", "data": <whole-card-body>}}

    where ``data`` is the card body itself (config + header + elements),
    NOT wrapped in another ``{"card": ...}``.
    """
    resp = P2CardActionTriggerResponse({})
    cb = CallBackCard()
    cb.type = "raw"
    cb.data = _json.loads(card_json)
    resp.card = cb
    return resp


def _toast_response(text: str) -> P2CardActionTriggerResponse:
    """Return a callback response with a toast and NO card mutation.

    Why this might help: when both ``card`` and ``toast`` are populated
    Feishu always renders the toast; when only the toast is set, Feishu is
    documented as keeping the existing card (which by now is our patched
    post-click state). If the empty-response path is what's reverting the
    card, this should stop the revert.
    """
    resp = P2CardActionTriggerResponse({})
    t = CallBackToast()
    t.type = "info"
    t.content = text
    resp.toast = t
    return resp


def handle_card_action(
    client: lark.Client,
    raw_event: Any,
    *,
    account_id: str,
) -> P2CardActionTriggerResponse:
    """Synchronous handler — registered on lark EventDispatcherHandler builder.

    Args:
        client: lark HTTP client used for outbound notice + card patch
        raw_event: ``P2CardActionTrigger``-like SDK event
        account_id: which Feishu account this event belongs to (token dedupe
            scope key)
    """
    try:
        operator_open_id = raw_event.event.operator.open_id
        token = raw_event.event.token
        action_value = raw_event.event.action.value or {}
        ctx = raw_event.event.context
        # lark P2CardActionTrigger.CallBackContext exposes ``open_message_id``
        # and ``open_chat_id``. ``chat_id`` (no ``open_`` prefix) is what
        # ``im.message.receive_v1`` uses, NOT card_action — different SDK
        # objects, easy to confuse. Fall back to either spelling so a future
        # SDK update that adds ``chat_id`` doesn't break us.
        message_id = getattr(ctx, "open_message_id", None) or getattr(ctx, "message_id", None)
        chat_id = getattr(ctx, "open_chat_id", None) or getattr(ctx, "chat_id", None)
        # Diagnostic: log the actual shape we got so we can see which fields
        # are populated by the SDK in this version.
        logger.info(
            "feishu_card_action_envelope_debug",
            ctx_attrs={
                a: getattr(ctx, a, None)
                for a in ("open_message_id", "message_id", "open_chat_id", "chat_id", "preview_token", "url")
            },
            message_id=message_id,
            chat_id=chat_id,
            operator_open_id=operator_open_id,
        )
    except AttributeError as exc:
        logger.warning("feishu_card_action_malformed_envelope", error=str(exc))
        return _empty_response()

    if not token or not str(token).strip():
        logger.warning("feishu_card_action_missing_token")
        return _empty_response()

    if not begin_token(token=token, account_id=account_id):
        logger.info(
            "feishu_approval_token_dedup", token=token, account_id=account_id,
        )
        cached = _recall_resolved_card(message_id)
        if cached is not None:
            return _card_response(cached)
        return _empty_response()

    try:
        decoded = decode_action(
            action_value=action_value,
            operator_open_id=operator_open_id,
            chat_id=chat_id,
        )
        if decoded.kind == "invalid":
            assert decoded.reason is not None
            logger.warning(
                "feishu_approval_invalid_action",
                reason=decoded.reason,
                operator_open_id=operator_open_id,
            )
            if chat_id:
                send_invalid_notice(
                    client, chat_id=chat_id, reason=decoded.reason,
                )
            complete_token(token=token, account_id=account_id)
            # If we already resolved this message earlier, keep the resolved
            # card (don't let a stray re-delivery from Feishu revert it).
            cached = _recall_resolved_card(message_id)
            if cached is not None:
                return _card_response(cached)
            return _empty_response()

        envelope = decoded.envelope or {}
        action_name = envelope.get("a", "")
        approval_id = (envelope.get("m") or {}).get("approval_id")

        if action_name not in (
            BERRY_APPROVAL_CONFIRM_ACTION, BERRY_APPROVAL_CANCEL_ACTION,
        ):
            logger.warning(
                "feishu_approval_unknown_action", action=action_name,
            )
            if chat_id:
                send_invalid_notice(
                    client, chat_id=chat_id, reason="malformed",
                )
            complete_token(token=token, account_id=account_id)
            return _empty_response()

        approved = action_name == BERRY_APPROVAL_CONFIRM_ACTION

        registry = get_approval_registry()
        # Read tool_name/args BEFORE resolve — channel.ask's finally cleans up
        # the metadata after wait returns, and resolve makes wait return.
        meta = registry.get_metadata(approval_id) if approval_id else {}
        tool_name = meta.get("tool_name", "?")
        args = meta.get("args", {}) or {}

        # ``resolve_ok`` controls whether we patch the card. If the future was
        # already cleaned up (timeout race), the channel side has already
        # written the timeout card — don't overwrite it.
        resolve_ok = False
        if approval_id:
            try:
                registry.resolve(approval_id, approved=approved)
                resolve_ok = True
                logger.info(
                    "feishu_approval_resolved",
                    approval_id=approval_id,
                    decision="allow" if approved else "deny",
                    operator_open_id=operator_open_id,
                )
            except (ApprovalNotFoundError, ApprovalAlreadyResolvedError) as exc:
                logger.info(
                    "feishu_approval_resolve_skipped",
                    approval_id=approval_id,
                    reason=type(exc).__name__,
                )

        # Build the resolved card once — used for the callback response,
        # the API patch, and the cached "this message's authoritative
        # post-click state" entry.
        resolved_card_json: str | None = None
        if resolve_ok:
            resolved_card_json = build_resolved_card(
                tool_name=tool_name,
                args=args,
                state="allowed" if approved else "denied",
            )
            if message_id:
                _remember_resolved_card(message_id, resolved_card_json)

        logger.info(
            "feishu_card_action_pre_patch",
            resolve_ok=resolve_ok, message_id=message_id, approved=approved,
        )
        if resolve_ok and message_id and resolved_card_json:
            patch_ok = update_card_by_message(
                client,
                message_id=message_id,
                card_json=resolved_card_json,
            )
            logger.info("feishu_card_action_post_patch", patch_ok=patch_ok)
        complete_token(token=token, account_id=account_id)

        # Always return the resolved card if we have one — either freshly
        # built (resolve_ok) or recalled from a previous delivery of the
        # same click (Feishu retries: duplicate token, same message_id, but
        # resolve fails because the future is already cleaned up). The
        # callback's response card is authoritative; without it Feishu
        # reverts the message to its pre-click rendering.
        card_to_return = resolved_card_json or _recall_resolved_card(message_id)
        if card_to_return is not None:
            return _card_response(card_to_return)
        return _empty_response()
    except Exception:
        # Unhandled exception during dispatch: release token so a Feishu
        # retry can take another swing (mirrors openclaw's RetryableError
        # branch). Approval future falls through to its 90s timeout.
        release_token(token=token, account_id=account_id)
        raise
