"""prometheus metric 单例 + 切面行为单测。

不验证完整 Counter / Histogram 内部状态(那是 prometheus_client 的责任),
只验证:
  - import 不抛异常 / 不报重复注册
  - LLM_CALLS / TOOL_CALLS 等暴露的对象类型对
  - labels 维度跟 spec 一致
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram
from prometheus_client import REGISTRY


def test_metrics_module_exports() -> None:
    """import 一次,所有 metric 都注册成功。"""
    from berry.observability import metrics

    assert isinstance(metrics.LLM_CALLS, Counter)
    assert isinstance(metrics.LLM_DURATION, Histogram)
    assert isinstance(metrics.LLM_TOKENS, Counter)
    assert isinstance(metrics.TOOL_CALLS, Counter)
    assert isinstance(metrics.TOOL_DURATION, Histogram)


def test_llm_calls_label_set() -> None:
    """LLM_CALLS 的 label 维度跟 spec 对得上。"""
    from berry.observability import metrics

    # prometheus_client Counter 没有公共 API 看 labelnames,
    # 走内部 _labelnames(2024 年仍稳定)
    assert metrics.LLM_CALLS._labelnames == ("model_logical", "api", "mode", "status")


def test_llm_tokens_label_set() -> None:
    from berry.observability import metrics

    assert metrics.LLM_TOKENS._labelnames == ("model_logical", "api", "kind")


def test_tool_calls_label_set() -> None:
    from berry.observability import metrics

    assert metrics.TOOL_CALLS._labelnames == ("tool", "status")


def test_metrics_registered_to_default_registry() -> None:
    """metric 都能在 prometheus_client 默认 registry 里找到。

    /metrics 端点(由 fastapi-instrumentator 服务)默认从这里读。
    """
    from berry.observability import metrics  # noqa: F401  ← 确保 import 触发注册

    names = {m.name for m in REGISTRY.collect()}
    assert "berry_llm_calls" in names
    assert "berry_llm_call_duration_seconds" in names
    assert "berry_llm_tokens" in names
    assert "berry_tool_calls" in names
    assert "berry_tool_call_duration_seconds" in names


def test_llm_counter_inc_does_not_raise() -> None:
    """切面调用 .labels(...).inc() 必须 work,不抛 LabelError。"""
    from berry.observability import metrics

    metrics.LLM_CALLS.labels(
        model_logical="test-model",
        api="anthropic_messages",
        mode="invoke",
        status="success",
    ).inc()


def test_tool_duration_observe_does_not_raise() -> None:
    from berry.observability import metrics

    metrics.TOOL_DURATION.labels(tool="bash").observe(0.5)
