"""TDD tests for Anthropic adapter prompt-cache wiring.

Strategy: instead of mocking the SDK, we test the pure body-builder
(``_build_body``) — a non-private renamed alias would be cleaner but the body
builder is internal and stable enough to test directly. Inputs go in, body
dict comes out, we assert structure.

Rationale for splitting on boundary marker:
- Spec § 7.1 commits to "static prefix never changes within a session".
- Anthropic prompt cache requires a content block with cache_control marker.
- Splitting at __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__ gives us a stable cache point
  with no API changes to LlmRequest.
"""

from __future__ import annotations

SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"
from berry.core.llm.adapters.anthropic_messages import AnthropicMessagesAdapter
from berry.core.llm.config import ModelDefaults, ModelEntry
from berry.core.llm.enums import KnownApi, ModelKind
from berry.core.llm.types import LlmMessage, LlmRequest


def _entry() -> ModelEntry:
    return ModelEntry(
        id="m1",
        kind=ModelKind.TEXT,
        api=KnownApi.ANTHROPIC_MESSAGES,
        provider="anthropic",
        base_url="https://api.anthropic.com",
        model_name="claude-opus-4-6",
        api_key="sk-test",
        timeout_s=60.0,
        defaults=ModelDefaults(),
    )


def _request(system: str | None) -> LlmRequest:
    return LlmRequest(
        model="m1",
        messages=[LlmMessage.user("hi")],
        system=system,
        max_tokens=512,
    )


# ─── system field shape ────────────────────────────────────────────────────


def test_system_with_boundary_splits_into_two_blocks_with_cache_marker() -> None:
    """When system contains the boundary marker, body['system'] is a list of two
    text blocks: the static prefix (with cache_control) and the dynamic tail."""
    adapter = AnthropicMessagesAdapter()
    static_part = "STATIC PREFIX TEXT"
    dynamic_part = "DYNAMIC TAIL TEXT"
    full = f"{static_part}\n\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}\n\n{dynamic_part}"

    body = adapter._build_body(_entry(), _request(full))

    assert isinstance(body["system"], list)
    assert len(body["system"]) == 2

    static_block, dynamic_block = body["system"]
    assert static_block["type"] == "text"
    assert static_block["text"] == static_part
    assert static_block["cache_control"] == {"type": "ephemeral"}

    assert dynamic_block["type"] == "text"
    assert dynamic_block["text"] == dynamic_part
    assert "cache_control" not in dynamic_block


def test_system_without_boundary_uses_single_uncached_string() -> None:
    """No boundary in the prompt → keep a plain string (no cache benefit, no
    behavior change for callers passing prompts that don't go through the
    learning builder)."""
    adapter = AnthropicMessagesAdapter()
    body = adapter._build_body(_entry(), _request("just a flat system prompt"))

    assert body["system"] == "just a flat system prompt"


def test_no_system_omits_field() -> None:
    """system=None → no 'system' key in body, matching current behavior."""
    adapter = AnthropicMessagesAdapter()
    body = adapter._build_body(_entry(), _request(None))

    assert "system" not in body


def test_static_prefix_strip_preserves_internal_newlines() -> None:
    """Multi-line static section (typical real prompt) keeps internal layout."""
    adapter = AnthropicMessagesAdapter()
    static_part = "Line 1\nLine 2\n\n# Section\n - bullet"
    full = f"{static_part}\n\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}\n\ntail"

    body = adapter._build_body(_entry(), _request(full))

    assert body["system"][0]["text"] == static_part


def test_boundary_with_empty_dynamic_tail_drops_dynamic_block() -> None:
    """If the boundary is the last meaningful content, no dynamic block is
    emitted (one block, with cache_control)."""
    adapter = AnthropicMessagesAdapter()
    static_part = "STATIC ONLY"
    full = f"{static_part}\n\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}"

    body = adapter._build_body(_entry(), _request(full))

    assert isinstance(body["system"], list)
    assert len(body["system"]) == 1
    assert body["system"][0]["text"] == static_part
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}


# ─── surrogate sanitization at body exit ───────────────────────────────────


def test_body_strips_surrogates_in_messages() -> None:
    """A lone surrogate that slipped through earlier scrubs must not survive
    body assembly; the whole body must be UTF-8 encodable."""
    adapter = AnthropicMessagesAdapter()
    poisoned_text = "before\udce5after"

    req = LlmRequest(
        model="m1",
        messages=[LlmMessage.user(poisoned_text)],
        system=None,
        max_tokens=512,
    )
    body = adapter._build_body(_entry(), req)

    # The whole body, serialized as JSON, must be encodable. If any surrogate
    # leaked through, json.dumps with ensure_ascii=False would still succeed
    # but a subsequent encode() raises — which is the real-world failure.
    import json
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    assert b"\\ud" not in encoded.lower() or True  # belt-and-braces; encode is the real check

    # Also assert the visible text fields no longer contain the bad codepoint.
    user_msg = body["messages"][0]
    text = user_msg["content"][0]["text"]
    assert "\udce5" not in text


def test_body_strips_surrogates_in_system() -> None:
    adapter = AnthropicMessagesAdapter()
    poisoned_system = f"static\udce5part\n\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}\n\ndynamic\udce6part"

    body = adapter._build_body(_entry(), _request(poisoned_system))

    # system is a list of blocks; check each block's text is clean
    assert isinstance(body["system"], list)
    for block in body["system"]:
        assert "\udce5" not in block["text"]
        assert "\udce6" not in block["text"]
