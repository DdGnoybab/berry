"""队列 key 派生 — `feishu:<account>:<chat_id>`。

对齐 openclaw `extensions/feishu/src/sequential-key.ts`(简化版)。

设计意图:**per-chat 串行,不 per-user**。同一对话里多人发言也串行处理,
避免 session 文件并发写出乱。MVP 只 DM 形态(chat 跟 user 一一对应),
后续接群聊时这个不变量不变 —— 群聊 session scope 怎么切是 conversation_id
那一层的事。
"""

from __future__ import annotations

from berry.channels.feishu.types import FeishuMessageEvent


def build_for_message(event: FeishuMessageEvent) -> str:
    """`feishu:<account_id>:<chat_id>`"""
    return f"feishu:{event.account_id}:{event.chat_id}"
