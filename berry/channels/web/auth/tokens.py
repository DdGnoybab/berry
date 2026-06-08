"""Session token helpers.

Cookie 里放原始 token (URL-safe base64);DB 里只存 sha256(token)。
"""

from __future__ import annotations

import hashlib
import secrets


def generate_token() -> str:
    """32 bytes 随机 → URL-safe base64 字符串(43 个字符)。"""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """sha256 hex digest of the raw token."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
