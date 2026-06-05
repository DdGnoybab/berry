"""Module-level singleton for the FeishuRuntimeAdapter.

对齐 openclaw `extensions/feishu/src/runtime.ts`(setter/getter 模式)。
原因:`bot.handle_feishu_message` 由 EventDispatcher 回调驱动,拿不到
依赖参数 — 必须从某处取实例。最直接是 module 单例,与 openclaw 一致。

启动顺序(`entrypoints/feishu.py`):
    adapter = FeishuRuntimeAdapter(runner=..., state_dir=..., default_user_id=...)
    set_feishu_runtime(adapter)
    await monitor_feishu_provider([account])
"""

from __future__ import annotations

from berry.channels.feishu.runtime_adapter import FeishuRuntimeAdapter

_runtime: FeishuRuntimeAdapter | None = None


def set_feishu_runtime(adapter: FeishuRuntimeAdapter) -> None:
    """启动期一次性注入。重复调用会覆盖。"""
    global _runtime
    _runtime = adapter


def get_feishu_runtime() -> FeishuRuntimeAdapter:
    """运行期取实例。未注入时 raise — 配置错误,应该在启动期就崩。"""
    if _runtime is None:
        raise RuntimeError(
            "FeishuRuntimeAdapter not set; call set_feishu_runtime(...) "
            "before starting the WS monitor"
        )
    return _runtime


def clear_feishu_runtime() -> None:
    """测试用。"""
    global _runtime
    _runtime = None
