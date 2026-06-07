"""Unit tests for berry.core.agent.error_recovery —
pure-function helpers AND the RetryingStreamCall state machine.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from berry.core.agent.error_recovery import (
    BASE_DELAY_MS,
    JITTER_RATIO,
    MAX_DELAY_MS,
    MAX_RETRIES,
    RETRYABLE_ERRORS,
    RetryingStreamCall,
    extract_retry_after,
    is_retryable,
    retry_delay_seconds,
)
from berry.core.llm.errors import (
    LlmAuthError,
    LlmConfigError,
    LlmInvalidRequestError,
    LlmRateLimitError,
    LlmServerError,
    LlmStreamError,
    LlmTimeoutError,
)
from berry.core.llm.types import (
    LlmMessage,
    LlmRequest,
    MessageStart,
    MessageStop,
    StreamEvent,
    TextBlock,
    TextDelta,
)
from berry.core.llm.enums import StopReason


# ─── retry_delay_seconds ─────────────────────────────────────────────────


def test_retry_delay_uses_retry_after_when_present() -> None:
    # given a server-supplied Retry-After
    delay = retry_delay_seconds(attempt=0, retry_after_seconds=7.5)

    # then we honor the server, ignoring the formula
    assert delay == 7.5


def test_retry_delay_ignores_zero_or_negative_retry_after() -> None:
    # zero / negative are nonsense — fall back to the formula
    rng = random.Random(0)
    random.seed(0)
    delay = retry_delay_seconds(attempt=0, retry_after_seconds=0)
    # base 500ms, jitter 0~125ms → bound checked, not exact value
    assert 0.5 <= delay <= 0.625 + 1e-9
    del rng  # keep linters quiet


def test_retry_delay_grows_exponentially_until_capped() -> None:
    # disable jitter for this check by seeding to make jitter call return 0.
    # uniform(0, x) returns 0 on first call when seeded with the right state.
    # Easier: assert bounds.
    bounds: list[tuple[float, float]] = []
    for attempt in range(8):
        base_ms = min(BASE_DELAY_MS * (2 ** attempt), MAX_DELAY_MS)
        lo = base_ms / 1000.0
        hi = (base_ms + base_ms * JITTER_RATIO) / 1000.0
        bounds.append((lo, hi))

    for attempt, (lo, hi) in enumerate(bounds):
        for _ in range(20):
            d = retry_delay_seconds(attempt=attempt)
            assert lo <= d <= hi + 1e-9, (
                f"attempt={attempt} got {d}, expected [{lo}, {hi}]"
            )


def test_retry_delay_caps_at_max() -> None:
    # attempt 10 would naively be 500 * 1024 = 512000ms, but is capped.
    delay = retry_delay_seconds(attempt=10)
    cap_seconds = MAX_DELAY_MS / 1000.0
    max_with_jitter = cap_seconds + cap_seconds * JITTER_RATIO
    assert delay <= max_with_jitter + 1e-9


def test_retry_delay_attempt_zero_starts_at_base() -> None:
    # The very first retry should wait at least BASE_DELAY_MS.
    delay = retry_delay_seconds(attempt=0)
    assert delay >= BASE_DELAY_MS / 1000.0


# ─── is_retryable / RETRYABLE_ERRORS ─────────────────────────────────────


def test_is_retryable_accepts_designated_classes() -> None:
    assert is_retryable(LlmRateLimitError("429"))
    assert is_retryable(LlmServerError("503"))
    assert is_retryable(LlmTimeoutError("timeout"))


def test_is_retryable_rejects_others() -> None:
    assert not is_retryable(LlmAuthError("401"))
    assert not is_retryable(LlmInvalidRequestError("400"))
    assert not is_retryable(LlmStreamError("stream broken"))
    assert not is_retryable(LlmConfigError("bad yaml"))
    assert not is_retryable(ValueError("unrelated"))


def test_retryable_errors_tuple_contains_only_expected_classes() -> None:
    # Lock the contract: changing this list is a deliberate decision, not a
    # silent drift. If someone adds StreamError here, a maintainer should see
    # this test fail and either bless the change (update the test + design
    # doc) or revert.
    assert RETRYABLE_ERRORS == (
        LlmRateLimitError,
        LlmServerError,
        LlmTimeoutError,
    )


# ─── extract_retry_after ─────────────────────────────────────────────────


def _exc_with_response(headers: dict[str, str] | None) -> Exception:
    """Craft an exception shaped like an Anthropic/OpenAI SDK error."""
    response = SimpleNamespace(headers=headers)
    exc = LlmRateLimitError("rate limited")
    # Mimic SDK convention: response is an attribute on the error
    exc.response = response  # type: ignore[attr-defined]
    return exc


def test_extract_retry_after_returns_none_without_response() -> None:
    exc = LlmRateLimitError("no response attached")
    assert extract_retry_after(exc) is None


def test_extract_retry_after_returns_none_when_headers_missing() -> None:
    exc = _exc_with_response(headers=None)
    assert extract_retry_after(exc) is None


def test_extract_retry_after_parses_seconds_lowercase_header() -> None:
    exc = _exc_with_response(headers={"retry-after": "3"})
    assert extract_retry_after(exc) == 3.0


def test_extract_retry_after_parses_seconds_titlecase_header() -> None:
    # Some SDKs hand back a plain dict where lookup is case-sensitive.
    exc = _exc_with_response(headers={"Retry-After": "5.5"})
    assert extract_retry_after(exc) == 5.5


def test_extract_retry_after_returns_none_for_http_date_format() -> None:
    # MVP doesn't parse HTTP-date; falls back to formula.
    exc = _exc_with_response(headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert extract_retry_after(exc) is None


def test_extract_retry_after_returns_none_for_negative_value() -> None:
    exc = _exc_with_response(headers={"retry-after": "-1"})
    assert extract_retry_after(exc) is None


def test_extract_retry_after_never_raises() -> None:
    # Even with a malformed shape, this helper must return None, not bubble.
    weird_response = SimpleNamespace(headers="not-a-mapping")
    exc: Any = LlmRateLimitError("weird")
    exc.response = weird_response
    # Will raise AttributeError if .get is called on str — verify it's caught
    # gracefully. Today's implementation only calls .get(), so str doesn't
    # raise but returns no match either; this test guards against future
    # regressions if someone changes the implementation.
    assert extract_retry_after(exc) is None


# ─── constants ───────────────────────────────────────────────────────────


def test_max_retries_is_positive() -> None:
    assert MAX_RETRIES > 0


# ─── RetryingStreamCall ──────────────────────────────────────────────────


# Per-model behavior the fake gateway mimics.  Two ways to drive a stream:
#   - error: pop next exception from a list and raise it on entry
#   - events: pop next list of StreamEvents and yield them in order
# A model whose error/event list is empty is "exhausted" and any further
# stream call raises RuntimeError so a buggy state machine surfaces fast.

class FakeGateway:
    """Minimal ModelGateway stand-in.

    Each model has an ordered script of "step"s. Each step is either:
      - an Exception class instance: stream() raises it (no events yielded)
      - a list[StreamEvent]: stream() yields them in order, then closes
      - a tuple (events_to_yield_first, exception_to_raise_after): yield N
        events then raise — used to test "stream already started" path.
    """

    def __init__(self, scripts: dict[str, list[Any]]) -> None:
        self._scripts = {model: list(steps) for model, steps in scripts.items()}
        self.calls: list[str] = []  # model_id per stream invocation
        # Surface a registry attribute so RetryingStreamCall users could
        # query it, though the retry shell itself doesn't consult it.
        self.registry = SimpleNamespace(get_fallback_chain=lambda _m: [])

    async def stream(self, model_id: str, _request: LlmRequest) -> AsyncIterator[StreamEvent]:
        self.calls.append(model_id)
        if model_id not in self._scripts or not self._scripts[model_id]:
            raise RuntimeError(f"FakeGateway: no script left for model {model_id!r}")
        step = self._scripts[model_id].pop(0)

        if isinstance(step, Exception):
            raise step

        if isinstance(step, tuple):
            events, exc = step
            for ev in events:
                yield ev
            raise exc

        # plain list of events
        for ev in step:
            yield ev


# Helpers ----------------------------------------------------------------


def _ok_events() -> list[StreamEvent]:
    """A minimal successful stream: start → text → stop."""
    return [
        MessageStart(id="msg_1", model="any"),
        TextDelta(text="hello"),
        MessageStop(stop_reason=StopReason.END_TURN),
    ]


def _request() -> LlmRequest:
    return LlmRequest(
        model="ignored",  # FakeGateway uses the model_id arg, not request.model
        messages=[LlmMessage(role="user", content=[TextBlock(text="hi")])],
        stream=True,
    )


async def _no_sleep(_seconds: float) -> None:
    """A sleep that returns immediately. Tests don't need real delays."""
    return None


async def _drain(call: RetryingStreamCall) -> list[StreamEvent]:
    out: list[StreamEvent] = []
    async for ev in call.run():
        out.append(ev)
    return out


# Cases ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_succeeds_after_one_rate_limit() -> None:
    # given the model fails once with 429, then succeeds
    gw = FakeGateway({
        "main": [LlmRateLimitError("429"), _ok_events()],
    })
    call = RetryingStreamCall(
        gateway=gw, request=_request(),
        initial_model="main", fallback_chain=[],
        sleep=_no_sleep,
    )

    # when
    events = await _drain(call)

    # then we got the success-path events, the model didn't switch,
    # and we made exactly two attempts on "main".
    assert [type(e).__name__ for e in events] == [
        "MessageStart", "TextDelta", "MessageStop",
    ]
    assert call.model_used == "main"
    assert gw.calls == ["main", "main"]
    assert call.attempts_used == 2


@pytest.mark.asyncio
async def test_retry_exhausts_then_raises_when_no_fallback() -> None:
    # given the model 5xxs forever and there's no fallback to walk
    errors = [LlmServerError("500")] * (MAX_RETRIES + 1)
    gw = FakeGateway({"main": errors})
    call = RetryingStreamCall(
        gateway=gw, request=_request(),
        initial_model="main", fallback_chain=[],
        sleep=_no_sleep,
    )

    # when / then it raises the last 5xx
    with pytest.raises(LlmServerError):
        await _drain(call)
    assert len(gw.calls) == MAX_RETRIES + 1
    assert call.remaining_chain == []


@pytest.mark.asyncio
async def test_fallback_engages_after_retries_exhausted() -> None:
    # given main fails MAX_RETRIES+1 times, then alt succeeds first try
    errors = [LlmServerError("500")] * (MAX_RETRIES + 1)
    gw = FakeGateway({
        "main": errors,
        "alt": [_ok_events()],
    })
    call = RetryingStreamCall(
        gateway=gw, request=_request(),
        initial_model="main", fallback_chain=["alt"],
        sleep=_no_sleep,
    )

    # when
    events = await _drain(call)

    # then we switched to alt, alt's events flowed through, and the
    # remaining_chain is empty (alt was the only fallback)
    assert call.model_used == "alt"
    assert gw.calls == (["main"] * (MAX_RETRIES + 1)) + ["alt"]
    assert len(events) == 3
    assert call.remaining_chain == []


@pytest.mark.asyncio
async def test_chain_exhausted_when_all_fallbacks_fail() -> None:
    # given main and alt both keep failing
    errors = [LlmServerError("500")] * (MAX_RETRIES + 1)
    gw = FakeGateway({
        "main": list(errors),
        "alt": list(errors),
    })
    call = RetryingStreamCall(
        gateway=gw, request=_request(),
        initial_model="main", fallback_chain=["alt"],
        sleep=_no_sleep,
    )

    # when / then
    with pytest.raises(LlmServerError):
        await _drain(call)
    # main + alt both attempted MAX_RETRIES+1 times each
    assert gw.calls.count("main") == MAX_RETRIES + 1
    assert gw.calls.count("alt") == MAX_RETRIES + 1
    assert call.model_used == "alt"  # last attempted


@pytest.mark.asyncio
async def test_timeout_is_treated_as_retryable() -> None:
    gw = FakeGateway({
        "main": [LlmTimeoutError("slow"), _ok_events()],
    })
    call = RetryingStreamCall(
        gateway=gw, request=_request(),
        initial_model="main", fallback_chain=[],
        sleep=_no_sleep,
    )

    events = await _drain(call)
    assert len(events) == 3
    assert gw.calls == ["main", "main"]


@pytest.mark.asyncio
async def test_auth_error_is_not_retried() -> None:
    # Auth errors are user-actionable (bad key); retrying wastes time.
    gw = FakeGateway({"main": [LlmAuthError("401")]})
    call = RetryingStreamCall(
        gateway=gw, request=_request(),
        initial_model="main", fallback_chain=["alt"],
        sleep=_no_sleep,
    )

    with pytest.raises(LlmAuthError):
        await _drain(call)
    assert gw.calls == ["main"]  # exactly one attempt; no retry, no fallback


@pytest.mark.asyncio
async def test_invalid_request_error_is_not_retried() -> None:
    gw = FakeGateway({"main": [LlmInvalidRequestError("bad json")]})
    call = RetryingStreamCall(
        gateway=gw, request=_request(),
        initial_model="main", fallback_chain=["alt"],
        sleep=_no_sleep,
    )

    with pytest.raises(LlmInvalidRequestError):
        await _drain(call)
    assert gw.calls == ["main"]


@pytest.mark.asyncio
async def test_error_after_first_event_is_not_retried() -> None:
    # The stream yields one event, THEN crashes. Retrying would produce
    # stitched output — see Q10 in the design doc.
    partial_then_die = (
        [MessageStart(id="msg_1", model="any"), TextDelta(text="hel")],
        LlmRateLimitError("mid-stream 429"),
    )
    gw = FakeGateway({
        "main": [partial_then_die, _ok_events()],
    })
    call = RetryingStreamCall(
        gateway=gw, request=_request(),
        initial_model="main", fallback_chain=["alt"],
        sleep=_no_sleep,
    )

    collected: list[StreamEvent] = []
    with pytest.raises(LlmRateLimitError):
        async for ev in call.run():
            collected.append(ev)

    # Two events were yielded before the crash; we did NOT retry.
    assert len(collected) == 2
    assert gw.calls == ["main"]


@pytest.mark.asyncio
async def test_remaining_chain_reflects_burned_entries() -> None:
    # given a 3-deep chain; main fails forever, alt1 fails forever, alt2 ok
    errors = [LlmServerError("500")] * (MAX_RETRIES + 1)
    gw = FakeGateway({
        "main": list(errors),
        "alt1": list(errors),
        "alt2": [_ok_events()],
    })
    call = RetryingStreamCall(
        gateway=gw, request=_request(),
        initial_model="main", fallback_chain=["alt1", "alt2"],
        sleep=_no_sleep,
    )

    await _drain(call)
    # main and alt1 burned; alt2 answered. Nothing left.
    assert call.model_used == "alt2"
    assert call.remaining_chain == []
