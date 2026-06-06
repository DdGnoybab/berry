"""Tests for card_action_dedupe — token claim/complete/release semantics."""

from __future__ import annotations

import pytest

from berry.channels.feishu.card_action_dedupe import (
    CARD_ACTION_TOKEN_TTL_MS,
    _reset_for_tests,
    begin_token,
    complete_token,
    release_token,
)


@pytest.fixture(autouse=True)
def _flush() -> None:
    _reset_for_tests()


def test_begin_first_time_returns_true() -> None:
    assert begin_token(token="t1", account_id="acc", now_ms=0) is True


def test_begin_same_token_again_returns_false() -> None:
    assert begin_token(token="t1", account_id="acc", now_ms=0) is True
    assert begin_token(token="t1", account_id="acc", now_ms=1) is False


def test_complete_keeps_dedupe_within_ttl() -> None:
    begin_token(token="t1", account_id="acc", now_ms=0)
    complete_token(token="t1", account_id="acc", now_ms=10)
    # within TTL, still blocked
    assert begin_token(token="t1", account_id="acc", now_ms=20) is False


def test_release_allows_retry() -> None:
    begin_token(token="t1", account_id="acc", now_ms=0)
    release_token(token="t1", account_id="acc")
    assert begin_token(token="t1", account_id="acc", now_ms=10) is True


def test_ttl_expiry_allows_re_claim() -> None:
    begin_token(token="t1", account_id="acc", now_ms=0)
    later = CARD_ACTION_TOKEN_TTL_MS + 1
    assert begin_token(token="t1", account_id="acc", now_ms=later) is True


def test_different_account_isolated() -> None:
    assert begin_token(token="t1", account_id="acc_a", now_ms=0) is True
    assert begin_token(token="t1", account_id="acc_b", now_ms=0) is True


def test_empty_token_is_rejected() -> None:
    assert begin_token(token="", account_id="acc", now_ms=0) is False
    assert begin_token(token="   ", account_id="acc", now_ms=0) is False
