"""Process-level dedupe for Feishu card.action.trigger events.

Feishu retries delivery of the same ``token`` if the handler hasn't responded
within their ack window. This module mirrors openclaw's
``processedCardActionTokens`` map: ``begin`` claims the token, ``complete``
keeps it claimed (it succeeded), ``release`` removes it (transient error,
allow retry).

15min TTL is a hard cap — well above Feishu's retry window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

CARD_ACTION_TOKEN_TTL_MS = 15 * 60 * 1000

Status = Literal["inflight", "completed"]


@dataclass
class _Entry:
    status: Status
    expires_at_ms: int


_processed: dict[str, _Entry] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _key(token: str, account_id: str) -> str:
    return f"{account_id}:{token.strip()}"


def _prune(now_ms: int) -> None:
    expired = [k for k, v in _processed.items() if v.expires_at_ms <= now_ms]
    for k in expired:
        _processed.pop(k, None)


def begin_token(*, token: str, account_id: str, now_ms: int | None = None) -> bool:
    """Claim the token. Returns True on first claim, False if already in flight
    or completed within TTL."""
    if now_ms is None:
        now_ms = _now_ms()
    if not token or not token.strip():
        return False
    _prune(now_ms)
    k = _key(token, account_id)
    existing = _processed.get(k)
    if existing is not None and existing.expires_at_ms > now_ms:
        return False
    _processed[k] = _Entry(status="inflight", expires_at_ms=now_ms + CARD_ACTION_TOKEN_TTL_MS)
    return True


def complete_token(*, token: str, account_id: str, now_ms: int | None = None) -> None:
    """Mark the token as completed; later ``begin_token`` calls within TTL
    still return False."""
    if now_ms is None:
        now_ms = _now_ms()
    if not token or not token.strip():
        return
    _processed[_key(token, account_id)] = _Entry(
        status="completed", expires_at_ms=now_ms + CARD_ACTION_TOKEN_TTL_MS,
    )


def release_token(*, token: str, account_id: str) -> None:
    """Used in transient-error paths to allow Feishu's next retry through."""
    if not token or not token.strip():
        return
    _processed.pop(_key(token, account_id), None)


def _reset_for_tests() -> None:
    """Test helper — flushes the global dict between tests."""
    _processed.clear()
