"""wire_logging 工具单测。

只测纯 helper:dump_sdk_object / cap_payload。
adapter 层的 wire 日志接入由集成测试 / 实际部署后看 berry.log 验证。
"""

from __future__ import annotations

from pydantic import BaseModel

from berry.observability.wire_logging import cap_payload, dump_sdk_object


# ─── dump_sdk_object ─────────────────────────────────────


def test_dump_pydantic_v2_model() -> None:
    class Foo(BaseModel):
        name: str
        age: int

    out = dump_sdk_object(Foo(name="x", age=42))
    assert out == {"name": "x", "age": 42}


def test_dump_dict_passthrough() -> None:
    assert dump_sdk_object({"a": 1}) == {"a": 1}


def test_dump_list_passthrough() -> None:
    assert dump_sdk_object([1, 2, 3]) == [1, 2, 3]


def test_dump_primitives_passthrough() -> None:
    assert dump_sdk_object("hello") == "hello"
    assert dump_sdk_object(42) == 42
    assert dump_sdk_object(None) is None


def test_dump_unknown_object_falls_back_to_str() -> None:
    class Weird:
        def __str__(self) -> str:
            return "weird-repr"

    assert dump_sdk_object(Weird()) == "weird-repr"


# ─── cap_payload ─────────────────────────────────────────


def test_cap_payload_short_string_unchanged() -> None:
    assert cap_payload("short") == "short"


def test_cap_payload_huge_string_truncated() -> None:
    huge = "x" * 2_000_000
    out = cap_payload(huge)
    assert "[hard-limit-truncated]" in out
    assert 1_000_000 < len(out) < 1_000_100


def test_cap_payload_recursive_dict() -> None:
    huge = "y" * 2_000_000
    payload = {"top": {"inner": huge, "ok": "small"}}
    out = cap_payload(payload)
    assert "[hard-limit-truncated]" in out["top"]["inner"]
    assert out["top"]["ok"] == "small"


def test_cap_payload_recursive_list() -> None:
    out = cap_payload(["short", "z" * 2_000_000])
    assert out[0] == "short"
    assert "[hard-limit-truncated]" in out[1]


def test_cap_payload_normal_lengths_pass_through() -> None:
    """正常对话用不到截断。100k token ≈ 400KB,远低于 1MB 上限。"""
    body = {
        "model": "claude-opus",
        "messages": [
            {"role": "user", "content": "请帮我看一下 redis 持久化"},
            {"role": "assistant", "content": "RDB 是周期性快照..."},
        ],
        "max_tokens": 4096,
    }
    out = cap_payload(body)
    assert out == body  # 完整保留,无任何修改
