"""Dedup key derivation — `(namespace, message_id) → 32-char hex`.

对齐 openclaw `extensions/feishu/src/dedupe-key.ts`。
单独成文件是为后续 V1 接入 plugin-state-store 时,namespace 计算逻辑能跨
文件复用(对应 openclaw `pluginStateNamespace`)。
"""

from __future__ import annotations

import hashlib
import re

_SAFE_NAMESPACE_RE = re.compile(r"[^a-zA-Z0-9_-]")


def normalize_namespace(namespace: str | None) -> str:
    """空 / None 视作 'global'。匹 openclaw `normalizeNamespace`。"""
    if namespace is None:
        return "global"
    trimmed = namespace.strip()
    return trimmed or "global"


def safe_namespace(namespace: str) -> str:
    """文件名安全的 namespace — 非字母数字下划线连字符全替换成 '_'。"""
    return _SAFE_NAMESPACE_RE.sub("_", namespace)


def dedupe_store_key(namespace: str, message_id: str) -> str:
    """`sha256("<ns>\\x00<message_id>") → 前 32 hex` — 与 openclaw 同算法。

    取前 32 位足够避碰(message_id 总共也就千万级别),又能控制 store key 短。
    """
    h = hashlib.sha256(f"{namespace}\x00{message_id}".encode("utf-8")).hexdigest()
    return h[:32]
