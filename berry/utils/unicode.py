"""Unicode hygiene helpers shared across stream / DB / HTTP boundaries.

Lone surrogate halves (U+D800-U+DFFF) leak in when an upstream byte stream
splits a multi-byte UTF-8 character at the wrong boundary. Python str keeps
them; ``str.encode("utf-8")`` then rejects them with ``surrogates_not_allowed``,
which crashes any subsequent HTTP body serialization.

Strip them at every inbound boundary that produces user-controlled text:

- LLM stream chunks (StreamAccumulator) — see berry.core.agent.stream_accumulator
- Tool results from web fetches — see berry.core.tools.web.*
- DB writes — see berry.core.db.repos.llm_log_repo

Single helper here, single place to fix if the strategy changes.
"""

from __future__ import annotations

from typing import Any


def strip_surrogates(text: str) -> str:
    """Drop lone surrogate halves so ``text.encode("utf-8")`` never raises.

    Idempotent. Valid multi-byte characters (CJK, emoji) pass through unchanged.
    """
    return text.encode("utf-8", errors="replace").decode("utf-8")


def strip_surrogates_deep(value: Any) -> Any:
    """Recursively apply :func:`strip_surrogates` to any string in a nested
    dict / list / scalar. Non-string values pass through untouched.

    Use when you need to sanitize a whole serializable payload (LLM request
    dump, tool args, DB JSON column) before persisting or re-encoding.
    """
    if isinstance(value, str):
        return strip_surrogates(value)
    if isinstance(value, dict):
        return {k: strip_surrogates_deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_surrogates_deep(item) for item in value]
    return value


__all__ = ["strip_surrogates", "strip_surrogates_deep"]
