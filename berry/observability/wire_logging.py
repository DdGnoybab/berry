"""LLM adapter 层的 wire-level 日志辅助。

定位:**记录真正发给厂商 HTTP API 的原始 body 和厂商真正返回的原始 body**,
不做任何 berry 中性化封装。

为什么不在 ModelGateway 层挂?
  ModelGateway 拿到的是 LlmRequest / LlmResponse (中性类型),已经被 adapter
  抽象过一层。admin 排查问题时常常需要确认「到底发了什么 JSON 给 Anthropic」、
  「Anthropic 真的返回了什么」,中性类型不够。

为什么 stream 不打每个 chunk?
  一次对话可能上千个 SSE 事件,每个都打日志会爆。所以 stream 累积事件序列,
  结束时一次性 dump。

事件命名:
  llm_wire_request       — 即将调 SDK,payload 是完整 SDK kwargs / HTTP body
  llm_wire_response      — invoke 收到 SDK response,payload 是 SDK 对象 dump
  llm_wire_stream_done   — stream 自然结束,payload 是事件序列 + 最终聚合
  llm_wire_failed        — 异常退出
"""

from __future__ import annotations

from typing import Any

# 单字段防御性硬上限(防极端攻击,正常对话用不到)
_HARD_LIMIT = 1_000_000
_HARD_TRUNC_SUFFIX = "…[hard-limit-truncated]"


def dump_sdk_object(obj: Any) -> Any:
    """尽力把 SDK 对象转成可 JSON 序列化的结构。

    优先级:
      1. pydantic v2 BaseModel.model_dump()
      2. pydantic v1 BaseModel.dict()
      3. obj 已经是 dict / list / 基本类型 -> 直接返
      4. 兜底:str(obj)
    """
    # pydantic v2
    if hasattr(obj, "model_dump") and callable(obj.model_dump):
        try:
            return obj.model_dump(mode="json")
        except Exception:
            pass
    # pydantic v1
    if hasattr(obj, "dict") and callable(obj.dict):
        try:
            return obj.dict()
        except Exception:
            pass
    # primitives / collections
    if isinstance(obj, (dict, list, str, int, float, bool)) or obj is None:
        return obj
    # last resort
    return str(obj)


def cap_payload(payload: Any) -> Any:
    """递归把 payload 里的字符串字段用硬上限保护一下。

    对 admin 看 prompt / response 没有任何影响(< 1MB),
    防极端 prompt 把日志炸掉。
    """
    if isinstance(payload, str):
        if len(payload) > _HARD_LIMIT:
            return payload[:_HARD_LIMIT] + _HARD_TRUNC_SUFFIX
        return payload
    if isinstance(payload, dict):
        return {k: cap_payload(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [cap_payload(x) for x in payload]
    return payload
