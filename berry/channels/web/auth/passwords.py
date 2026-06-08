"""Password hashing using bcrypt.

bcrypt 自带 salt,hash 后是一段独立字符串,verify 时不需要单独存 salt。
"""

from __future__ import annotations

import bcrypt


def hash_password(plain: str) -> str:
    """Return bcrypt hash of the password as a UTF-8 string."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time check; returns False if hashed is empty / malformed."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False
