"""TDD tests for the shared surrogate-stripping helper.

Lone surrogates (U+D800-U+DFFF) leak in when an upstream byte stream cuts a
multi-byte UTF-8 character at the wrong boundary. Python keeps them in the
str, but `str.encode('utf-8')` rejects them with surrogates_not_allowed —
which crashes any later HTTP body serialization.
"""

from __future__ import annotations

from berry.utils.unicode import strip_surrogates


def test_returns_plain_text_unchanged() -> None:
    assert strip_surrogates("hello world") == "hello world"


def test_keeps_valid_multibyte_chars() -> None:
    """Real CJK / emoji must survive untouched."""
    text = "你好 redis 🚀 — 中文测试"
    assert strip_surrogates(text) == text


def test_strips_lone_low_surrogate() -> None:
    """A trailing lone low surrogate is replaced, leaving the rest intact."""
    bad = "ok\udce5 tail"
    cleaned = strip_surrogates(bad)
    cleaned.encode("utf-8")  # must not raise
    assert "tail" in cleaned
    assert "\udce5" not in cleaned


def test_strips_lone_high_surrogate() -> None:
    bad = "head \ud83d  trail"  # high surrogate followed by space (no pair)
    cleaned = strip_surrogates(bad)
    cleaned.encode("utf-8")
    assert "\ud83d" not in cleaned


def test_handles_only_surrogates() -> None:
    """All-surrogate input becomes safely encodable, possibly empty/replaced."""
    cleaned = strip_surrogates("\udce5\udce6")
    cleaned.encode("utf-8")  # must not raise


def test_idempotent() -> None:
    bad = "ok\udce5 tail"
    once = strip_surrogates(bad)
    twice = strip_surrogates(once)
    assert once == twice


def test_preserves_well_formed_emoji_pair() -> None:
    """A correctly-paired surrogate (modeled in Python as a single codepoint
    on wide builds, or as an explicit pair) should survive."""
    rocket = "🚀"
    rocket.encode("utf-8")  # sanity
    assert strip_surrogates(rocket) == rocket
