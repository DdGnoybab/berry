"""Message dedup — 内存 LRU + 磁盘 JSON 持久化,跨 WS 重连 / 进程重启生效。

对齐 openclaw `extensions/feishu/src/dedup.ts`。openclaw 用 plugin-state-store
做持久化,berry 没那个抽象,直接用 JSON 文件,简化但语义一致:

- TTL 24h(`DEDUP_TTL_MS`)— 超时条目读出来时即丢弃
- 内存 LRU 1000 条(`MEMORY_MAX_SIZE`)— 防 long-running 进程内存爆
- 磁盘上限 10000 条(`STORE_MAX_ENTRIES`)— 超时清理 + 容量上限二选一先到的生效
- 文件路径 `<state_dir>/feishu/dedup/<safe_namespace>.json`
- 文件损坏视作空(WARN 日志,不 raise)— 罕见且不致命

API:
- `seen(namespace, message_id) -> bool`:已见返回 True;未见返回 False **并** 标记
  为已见(原子,不需要二次 mark)。等同于 openclaw `tryBeginFeishuMessageProcessing`
  的「检查 + 占位」语义,但 MVP 不分 begin/release(没有 worker 模型),
  视一次 seen 即处理完毕。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from berry.channels.feishu.dedupe_key import (
    dedupe_store_key,
    normalize_namespace,
    safe_namespace,
)
from berry.observability.logging import get_logger

# 与 openclaw 同款常量
DEDUP_TTL_MS: int = 24 * 60 * 60 * 1000   # 24h
MEMORY_MAX_SIZE: int = 1_000
STORE_MAX_ENTRIES: int = 10_000

logger = get_logger(__name__)


@dataclass
class _Entry:
    seen_at_ms: int  # epoch ms


def _now_ms() -> int:
    return int(time.time() * 1000)


def _is_recent(seen_at_ms: int, now_ms: int, ttl_ms: int = DEDUP_TTL_MS) -> bool:
    return now_ms - seen_at_ms < ttl_ms


class FeishuDedup:
    """单 namespace 的 dedup 实例。多 namespace 用多实例,实例内自维护内存 + 磁盘。

    线程安全:不保证 — MVP 单 asyncio 事件循环顺序消费事件,无并发写。
    """

    def __init__(
        self,
        namespace: str,
        state_dir: Path,
        *,
        ttl_ms: int = DEDUP_TTL_MS,
        memory_max: int = MEMORY_MAX_SIZE,
        store_max: int = STORE_MAX_ENTRIES,
    ) -> None:
        self._ns = normalize_namespace(namespace)
        self._ttl_ms = ttl_ms
        self._memory_max = memory_max
        self._store_max = store_max
        self._memory: dict[str, _Entry] = {}
        self._file = state_dir / "feishu" / "dedup" / f"{safe_namespace(self._ns)}.json"
        self._disk: dict[str, _Entry] = self._load()

    # -- public API ----------------------------------------------------------

    def seen(self, message_id: str) -> bool:
        """返回 True 表示之前已经见过这个 message_id;False 表示是新消息(并已记下)。"""
        message_id = (message_id or "").strip()
        if not message_id:
            # 没 id 的事件不 dedup — 直接当新消息处理(让上层决定要不要丢)
            return False

        key = dedupe_store_key(self._ns, message_id)
        now = _now_ms()

        # 先查内存(快路径)
        ent = self._memory.get(key)
        if ent and _is_recent(ent.seen_at_ms, now, self._ttl_ms):
            return True

        # 再查磁盘
        ent_disk = self._disk.get(key)
        if ent_disk and _is_recent(ent_disk.seen_at_ms, now, self._ttl_ms):
            # 重启后第一次撞上 — 把它放进内存,并算作 hit
            self._memory[key] = ent_disk
            return True

        # 未见 — 记下来,内存 + 磁盘
        new_entry = _Entry(seen_at_ms=now)
        self._memory[key] = new_entry
        self._disk[key] = new_entry
        self._prune(now)
        self._save()
        return False

    # -- 内部 -----------------------------------------------------------------

    def _prune(self, now_ms: int) -> None:
        """清过期 + 内存超限按 seen_at 升序裁。"""
        # 内存
        for key, ent in list(self._memory.items()):
            if not _is_recent(ent.seen_at_ms, now_ms, self._ttl_ms):
                del self._memory[key]
        if len(self._memory) > self._memory_max:
            ordered = sorted(self._memory.items(), key=lambda it: it[1].seen_at_ms)
            for key, _ in ordered[: len(self._memory) - self._memory_max]:
                del self._memory[key]

        # 磁盘
        for key, ent in list(self._disk.items()):
            if not _is_recent(ent.seen_at_ms, now_ms, self._ttl_ms):
                del self._disk[key]
        if len(self._disk) > self._store_max:
            ordered = sorted(self._disk.items(), key=lambda it: it[1].seen_at_ms)
            for key, _ in ordered[: len(self._disk) - self._store_max]:
                del self._disk[key]

    def _load(self) -> dict[str, _Entry]:
        if not self._file.exists():
            return {}
        try:
            raw = json.loads(self._file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "feishu_dedup_file_corrupt",
                path=str(self._file),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return {}
        if not isinstance(raw, dict):
            logger.warning("feishu_dedup_file_invalid_shape", path=str(self._file))
            return {}
        out: dict[str, _Entry] = {}
        now = _now_ms()
        for k, v in raw.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, dict) and isinstance(v.get("seen_at_ms"), int):
                if _is_recent(v["seen_at_ms"], now, self._ttl_ms):
                    out[k] = _Entry(seen_at_ms=v["seen_at_ms"])
        return out

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: {"seen_at_ms": e.seen_at_ms} for k, e in self._disk.items()}
        tmp = self._file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._file)
