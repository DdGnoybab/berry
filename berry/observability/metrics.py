"""Prometheus 业务 metric 单例定义。

设计:
- HTTP metric 由 prometheus-fastapi-instrumentator 自动产出(在 main.py 接),
  这里只定义 LLM / Tool 两类业务 metric
- 模块级单例,import 一次即注册,**不要重复定义**(prometheus_client 会报错)
- 切面位置:
    - LLM:berry/core/llm/gateway.py(invoke / stream 两个入口)
    - Tool:berry/core/agent/runtime.py(tool dispatcher 唯一调用点)

Spec:docs/superpowers/specs/2026-06-15-monitoring-design.md
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# ─── LLM ───────────────────────────────────────────────────

# 调用次数。基数估算:5 model × 2 api × 2 mode × 2 status = 40 series,安全。
LLM_CALLS = Counter(
    "berry_llm_calls_total",
    "LLM 调用总次数",
    ["model_logical", "api", "mode", "status"],
)

# 调用耗时。bucket 按 LLM 调用真实分布:1s 起跳,60s 顶。
LLM_DURATION = Histogram(
    "berry_llm_call_duration_seconds",
    "LLM 调用耗时(秒)",
    ["model_logical", "api", "mode"],
    buckets=(1, 2, 5, 10, 20, 30, 60),
)

# token 消耗。kind ∈ input / output / cache_read / cache_write。
LLM_TOKENS = Counter(
    "berry_llm_tokens_total",
    "LLM token 消耗(累计)",
    ["model_logical", "api", "kind"],
)


# ─── Tool ──────────────────────────────────────────────────

# 调用次数。tool ~14 个 × status 2 个 = ~28 series。
TOOL_CALLS = Counter(
    "berry_tool_calls_total",
    "Tool 调用总次数",
    ["tool", "status"],
)

# 调用耗时。bucket 跨度大:bash 等可能秒级,read_file 毫秒级,web_fetch 分钟级。
TOOL_DURATION = Histogram(
    "berry_tool_call_duration_seconds",
    "Tool 调用耗时(秒)",
    ["tool"],
    buckets=(0.01, 0.1, 1, 5, 30, 60, 300),
)


__all__ = [
    "LLM_CALLS",
    "LLM_DURATION",
    "LLM_TOKENS",
    "TOOL_CALLS",
    "TOOL_DURATION",
]
