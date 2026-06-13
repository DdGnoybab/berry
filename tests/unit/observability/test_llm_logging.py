"""LLM 切面日志摘要工具的单测。

核心设计校验:**完整保真,不做语义截断**(admin 实际用法是 grep query 子串
定位到那次调用,然后看完整请求/响应)。
"""

from __future__ import annotations

from berry.core.llm.enums import StopReason
from berry.core.llm.types import (
    LlmMessage,
    LlmRequest,
    LlmResponse,
    LlmTool,
    TextBlock,
    ToolUseBlock,
    Usage,
)
from berry.observability.llm_logging import (
    summarize_request,
    summarize_response,
    summarize_stream_outcome,
)


# ─── summarize_request ────────────────────────────────────


def test_summarize_request_basic_text() -> None:
    req = LlmRequest(
        model="claude-opus",
        messages=[LlmMessage.user("hello"), LlmMessage.assistant("hi")],
        max_tokens=1000,
    )
    out = summarize_request(req)
    assert out["model"] == "claude-opus"
    assert out["message_count"] == 2
    assert out["total_chars"] == 7  # "hello" + "hi"
    assert out["system_chars"] == 0
    assert out["has_tools"] is False
    assert out["stream"] is False

    payload = out["payload"]
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "user"
    assert payload["messages"][0]["blocks"][0]["text"] == "hello"
    assert payload["messages"][1]["blocks"][0]["text"] == "hi"


def test_summarize_request_keeps_full_user_query_for_grep() -> None:
    """用户长 query 必须完整保留,admin 后续 grep 子串能命中。"""
    long_query = (
        "请用 redis 实现一个分布式锁,"
        "考虑过期时间、可重入、续期、宕机自动释放,"
        "并对比 redlock 算法和单实例 setnx 的取舍。" * 50  # 重复出长 query
    )
    req = LlmRequest(model="m", messages=[LlmMessage.user(long_query)])
    out = summarize_request(req)
    payload_text = out["payload"]["messages"][0]["blocks"][0]["text"]
    # 没有任何截断
    assert payload_text == long_query
    assert "分布式锁" in payload_text
    assert "redlock" in payload_text


def test_summarize_request_keeps_full_system_prompt() -> None:
    """system 长 prompt 也保留 — 跟 message 一样,完整 grep 能命中。"""
    system = "You are berry. " + ("详细规则。" * 1000)
    req = LlmRequest(model="m", messages=[LlmMessage.user("x")], system=system)
    out = summarize_request(req)
    assert out["system_chars"] == len(system)
    # 完整 system 进了 payload
    assert out["payload"]["system"] == system


def test_summarize_request_with_tools() -> None:
    tools = [
        LlmTool(
            name="search",
            description="search the web",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        ),
    ]
    req = LlmRequest(model="m", messages=[LlmMessage.user("x")], tools=tools)
    out = summarize_request(req)
    assert out["has_tools"] is True
    tool_dump = out["payload"]["tools"][0]
    assert tool_dump["name"] == "search"
    assert tool_dump["description"] == "search the web"
    assert tool_dump["input_schema"]["properties"]["q"]["type"] == "string"


def test_summarize_request_hard_caps_extreme_length() -> None:
    """极端边界: > 1MB 才截断,正常对话用不到。"""
    extreme = "x" * 2_000_000
    req = LlmRequest(model="m", messages=[LlmMessage.user(extreme)])
    out = summarize_request(req)
    text = out["payload"]["messages"][0]["blocks"][0]["text"]
    assert "[hard-limit-truncated]" in text
    # 截断到 1MB + suffix
    assert 1_000_000 < len(text) < 1_000_100


# ─── summarize_response ───────────────────────────────────


def test_summarize_response_basic() -> None:
    resp = LlmResponse(
        id="msg_123",
        model="m",
        content=[TextBlock(text="answer")],
        stop_reason=StopReason.END_TURN,
        usage=Usage(input_tokens=10, output_tokens=5),
    )
    out = summarize_response(resp)
    assert out["response_id"] == "msg_123"
    assert out["content_blocks"] == 1
    assert out["output_chars"] == 6
    assert out["input_tokens"] == 10
    assert out["output_tokens"] == 5
    assert out["payload"]["content"][0]["text"] == "answer"


def test_summarize_response_keeps_full_long_answer() -> None:
    long_answer = "redis 学习总结:\n" + ("RDB 是快照机制。" * 500)
    resp = LlmResponse(
        id="x",
        model="m",
        content=[TextBlock(text=long_answer)],
        stop_reason=StopReason.END_TURN,
        usage=Usage(),
    )
    out = summarize_response(resp)
    assert out["payload"]["content"][0]["text"] == long_answer


def test_summarize_response_with_tool_use_keeps_full_input() -> None:
    """tool_use 的 input 是 dict,不能丢字段。"""
    tool_input = {"query": "redis 持久化", "filters": {"lang": "zh", "year": 2026}}
    resp = LlmResponse(
        id="msg_x",
        model="m",
        content=[
            TextBlock(text="let me check"),
            ToolUseBlock(id="tu_1", name="search", input=tool_input),
        ],
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(),
    )
    out = summarize_response(resp)
    assert out["content_blocks"] == 2
    payload_content = out["payload"]["content"]
    assert payload_content[1]["type"] == "tool_use"
    assert payload_content[1]["name"] == "search"
    assert payload_content[1]["input"] == tool_input


# ─── summarize_stream_outcome ────────────────────────────


def test_summarize_stream_outcome_keeps_full_text() -> None:
    """流式累积出来的完整文本完全保留。"""
    streamed = "redis 学习路径:\n1. 数据结构\n2. 持久化\n3. 高可用\n" * 200
    out = summarize_stream_outcome(
        accumulated_text=streamed,
        accumulated_thinking="",
        tool_calls=[],
        stop_reason="end_turn",
        input_tokens=20,
        output_tokens=300,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert out["output_chars"] == len(streamed)
    assert out["payload"]["text"] == streamed


def test_summarize_stream_outcome_keeps_thinking() -> None:
    out = summarize_stream_outcome(
        accumulated_text="answer",
        accumulated_thinking="先想想这个问题应该从持久化角度入手...",
        tool_calls=[],
        stop_reason="end_turn",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert "持久化角度" in out["payload"]["thinking"]
    assert out["thinking_chars"] > 0


def test_summarize_stream_outcome_no_thinking_omits_field() -> None:
    out = summarize_stream_outcome(
        accumulated_text="answer",
        accumulated_thinking="",
        tool_calls=[],
        stop_reason="end_turn",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert "thinking" not in out["payload"]


def test_summarize_stream_outcome_with_tool_calls() -> None:
    tool_calls = [
        {"id": "tu_1", "name": "search", "input_chars": 42},
        {"id": "tu_2", "name": "read", "input_chars": 18},
    ]
    out = summarize_stream_outcome(
        accumulated_text="",
        accumulated_thinking="",
        tool_calls=tool_calls,
        stop_reason="tool_use",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert out["tool_call_count"] == 2
    assert out["payload"]["tool_calls"] == tool_calls


def test_summarize_stream_outcome_unknown_stop() -> None:
    out = summarize_stream_outcome(
        accumulated_text="",
        accumulated_thinking="",
        tool_calls=[],
        stop_reason=None,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
    assert out["stop_reason"] == "unknown"
