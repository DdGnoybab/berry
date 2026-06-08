"""Session token generator + sha256 hasher."""

from berry.channels.web.auth.tokens import generate_token, hash_token


def test_generate_token_is_url_safe() -> None:
    token = generate_token()
    # URL-safe base64 ⇒ only [A-Za-z0-9_-]
    allowed = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert all(c in allowed for c in token)


def test_generate_token_is_unique_enough() -> None:
    """Birthday-paradox sanity: 100 tokens, all distinct."""
    tokens = {generate_token() for _ in range(100)}
    assert len(tokens) == 100


def test_hash_token_is_deterministic() -> None:
    raw = "fixed-token"
    assert hash_token(raw) == hash_token(raw)


def test_hash_token_differs_for_different_inputs() -> None:
    assert hash_token("a") != hash_token("b")


def test_hash_token_returns_64_hex_chars() -> None:
    """sha256 hex digest is always 64 chars."""
    h = hash_token("anything")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
