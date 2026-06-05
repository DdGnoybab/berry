"""dedup 持久化 + LRU 行为测试 — 对应 openclaw `dedup.test.ts`。"""

from __future__ import annotations

from pathlib import Path

import pytest

from berry.channels.feishu.dedup import FeishuDedup


def test_first_seen_returns_false_then_true(tmp_path: Path) -> None:
    d = FeishuDedup("acct1", state_dir=tmp_path)
    assert d.seen("om_1") is False  # 新消息
    assert d.seen("om_1") is True   # 第二次见


def test_different_message_ids_independent(tmp_path: Path) -> None:
    d = FeishuDedup("acct1", state_dir=tmp_path)
    assert d.seen("om_a") is False
    assert d.seen("om_b") is False
    assert d.seen("om_a") is True
    assert d.seen("om_b") is True


def test_persistent_across_instances(tmp_path: Path) -> None:
    d1 = FeishuDedup("acct1", state_dir=tmp_path)
    assert d1.seen("om_1") is False

    # 模拟进程重启 — 新建一个实例,读同一个 state_dir
    d2 = FeishuDedup("acct1", state_dir=tmp_path)
    assert d2.seen("om_1") is True, "重启后老消息应被识别为已见"


def test_namespace_isolation(tmp_path: Path) -> None:
    d_a = FeishuDedup("acct_a", state_dir=tmp_path)
    d_b = FeishuDedup("acct_b", state_dir=tmp_path)
    assert d_a.seen("om_x") is False
    assert d_b.seen("om_x") is False  # 不同 namespace 互不影响


def test_empty_message_id_not_dedupped(tmp_path: Path) -> None:
    d = FeishuDedup("acct1", state_dir=tmp_path)
    assert d.seen("") is False
    assert d.seen("") is False  # 空 id 永远视作 new(由上层决定要不要丢)


def test_corrupt_file_treated_as_empty(tmp_path: Path) -> None:
    # 先创建 dedup 路径
    d1 = FeishuDedup("acct1", state_dir=tmp_path)
    d1.seen("om_1")  # 写一次磁盘

    # 把磁盘文件污染掉
    file = tmp_path / "feishu" / "dedup" / "acct1.json"
    assert file.exists()
    file.write_text("not valid json {{{", encoding="utf-8")

    # 再开新实例,不应 raise
    d2 = FeishuDedup("acct1", state_dir=tmp_path)
    assert d2.seen("om_1") is False  # 损坏 = 当作空


def test_ttl_expiry(tmp_path: Path) -> None:
    # 用极短 TTL 模拟过期
    d = FeishuDedup("acct1", state_dir=tmp_path, ttl_ms=1)

    assert d.seen("om_1") is False
    import time as _t

    _t.sleep(0.01)  # > 1ms
    assert d.seen("om_1") is False  # 过期了,视作新消息


def test_memory_lru_eviction(tmp_path: Path) -> None:
    # memory_max=3,塞 5 条 — 最早的 2 条应被踢出内存
    d = FeishuDedup("acct1", state_dir=tmp_path, memory_max=3, store_max=10_000)

    for i in range(5):
        assert d.seen(f"om_{i}") is False

    # 全部还在磁盘 (store_max=10000),所以重新查仍然命中
    for i in range(5):
        assert d.seen(f"om_{i}") is True
