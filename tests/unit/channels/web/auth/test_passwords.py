"""bcrypt password hashing roundtrip + edge cases."""

from berry.channels.web.auth.passwords import hash_password, verify_password


def test_hash_then_verify_succeeds() -> None:
    h = hash_password("hunter2")
    assert verify_password("hunter2", h) is True


def test_verify_rejects_wrong_password() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("wrong", h) is False


def test_verify_rejects_empty_hash() -> None:
    assert verify_password("anything", "") is False


def test_verify_rejects_malformed_hash() -> None:
    assert verify_password("x", "not-a-bcrypt-hash") is False


def test_two_hashes_of_same_password_differ() -> None:
    """Per-call salt makes hash output non-deterministic."""
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    assert verify_password("same", a)
    assert verify_password("same", b)
