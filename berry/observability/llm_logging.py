"""LLM 调用切面日志辅助。

ModelGateway.invoke / stream 是 LLM 调用唯一入口,所以切面挂这一处就覆盖所有路径。

设计要求(由 admin 实际诊断场景反推):
- **完整保真**:用户后续会搜某句 query 的子串 → 必须能命中那次请求的 messages,
  也能命中那次响应的 content。**不做语义截断 / 预览**。
- 元信息内联(model / message_count / total_chars / duration_ms 等)便于一眼扫
- 完整 request / response 进 `payload` 字段,前端默认折叠,点开看
- token 类敏感字段不出现在 LlmRequest 里(adapter 才注入),所以 payload 安全。
  system prompt 也按用户授权完整入日志(berry 是单租户/小团队,admin 自己看自己 prompt)
- 单字段硬上限只防极端攻击(>1MB),正常对话远不到

事件命名(对应 docs/logging-conventions.md):
  llm_call_start    — 进入 invoke / stream 之前
  llm_call_done     — 成功收尾(invoke 拿到 response / stream 自然结束)
  llm_call_failed   — 异常退出
"""

from __future__ import annotations

from typing import Any

from berry.core.llm.types import LlmRequest, LlmResponse


# 防御性硬上限:单字段超过 1MB 才截断,正常对话用不到。
# 100k tokens 中文 ≈ 400KB,英文 ≈ 600KB,均不会触发。
_HARD_LIMIT = 1_000_000
_HARD_TRUNC_SUFFIX = "…[hard-limit-truncated]"


def summarize_request(request: LlmRequest) -> dict[str, Any]:
    """把 LlmRequest 拍扁成可入日志的 dict。

    顶层字段(grep 友好):
      model / message_count / system_chars / total_chars / has_tools / stream
    完整内容放 payload(展开看):
      messages(每条 role + 完整 content blocks)
      system(完整文本)
      tools / max_tokens / temperature / top_p / stop / metadata
    """
    total_chars = sum(_message_chars(m) for m in request.messages)
    system_chars = len(request.system) if request.system else 0

    payload: dict[str, Any] = {
        "messages": [_dump_message(m) for m in request.messages],
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
        "top_p": request.top_p,
        "stop": request.stop,
        "metadata": request.metadata,
    }
    if request.system:
        payload["system"] = _hard_cap(request.system)
    if request.tools:
        payload["tools"] = [
            {
                "name": t.name,
                "description": _hard_cap(t.description),
                "input_schema": t.input_schema,
            }
            for t in request.tools
        ]

    return {
        "model": request.model,
        "message_count": len(request.messages),
        "system_chars": system_chars,
        "total_chars": total_chars,
        "has_tools": bool(request.tools),
        "stream": request.stream,
        "payload": payload,
    }


def summarize_response(response: LlmResponse) -> dict[str, Any]:
    """把 LlmResponse 拍扁。

    顶层:id / stop_reason / content_blocks / output_chars / input_tokens / output_tokens
    详细:content (完整 blocks,展开看)
    """
    content_blocks = len(response.content)
    output_chars = sum(_block_chars(b) for b in response.content)

    payload: dict[str, Any] = {
        "content": [_dump_block(b) for b in response.content],
    }

    return {
        "response_id": response.id,
        "stop_reason": response.stop_reason.value
        if hasattr(response.stop_reason, "value")
        else str(response.stop_reason),
        "content_blocks": content_blocks,
        "output_chars": output_chars,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_tokens": response.usage.cache_read_tokens,
        "cache_write_tokens": response.usage.cache_write_tokens,
        "payload": payload,
    }


def summarize_stream_outcome(
    accumulated_text: str,
    accumulated_thinking: str,
    tool_calls: list[dict[str, Any]],
    stop_reason: str | None,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> dict[str, Any]:
    """流式调用收尾时,把累积出的内容拍扁。

    stream 没有完整 LlmResponse 对象,调用方自己累积文字 / thinking / tool_calls / usage,
    传进来这边渲染 payload。**完整文本不截断**,跟 invoke 路径行为一致。
    """
    payload: dict[str, Any] = {
        "text": _hard_cap(accumulated_text),
        "tool_calls": tool_calls,
    }
    if accumulated_thinking:
        payload["thinking"] = _hard_cap(accumulated_thinking)

    return {
        "stop_reason": stop_reason or "unknown",
        "output_chars": len(accumulated_text),
        "thinking_chars": len(accumulated_thinking),
        "tool_call_count": len(tool_calls),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "payload": payload,
    }


# ─── helpers ──────────────────────────────────────────────


def _message_chars(msg: Any) -> int:
    """累计一条 message 中所有文本块的字符数(估算)。"""
    total = 0
    for block in msg.content:
        total += _block_chars(block)
    return total


def _block_chars(block: Any) -> int:
    btype = getattr(block, "type", None)
    if btype in ("text", "thinking"):
        return len(getattr(block, "text", "") or "")
    if btype == "tool_use":
        return len(str(getattr(block, "input", "") or ""))
    if btype == "tool_result":
        return len(getattr(block, "output", "") or "")
    return 0


def _dump_message(msg: Any) -> dict[str, Any]:
    return {
        "role": msg.role,
        "blocks": [_dump_block(b) for b in msg.content],
    }


def _dump_block(block: Any) -> dict[str, Any]:
    """完整 dump 一个 content block,不截断语义。

    只在单字段超 1MB 才硬截断(防极端边界),正常对话不会触发。
    """
    btype = getattr(block, "type", "unknown")
    if btype == "text":
        return {"type": "text", "text": _hard_cap(getattr(block, "text", ""))}
    if btype == "thinking":
        return {"type": "thinking", "text": _hard_cap(getattr(block, "text", ""))}
    if btype == "tool_use":
        return {
            "type": "tool_use",
            "id": getattr(block, "id", ""),
            "name": getattr(block, "name", ""),
            "input": getattr(block, "input", {}),
        }
    if btype == "tool_result":
        return {
            "type": "tool_result",
            "tool_use_id": getattr(block, "tool_use_id", ""),
            "is_error": getattr(block, "is_error", False),
            "output": _hard_cap(getattr(block, "output", "")),
        }
    return {"type": str(btype)}


def _hard_cap(text: str) -> str:
    """只在极端长度时截断(防御性)。

    1MB 上限远超正常 LLM 输入输出,正常 grep / 看 prompt 都不受影响。
    """
    if len(text) <= _HARD_LIMIT:
        return text
    return text[:_HARD_LIMIT] + _HARD_TRUNC_SUFFIX
