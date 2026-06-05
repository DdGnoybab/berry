"""Conversation ID 构造 — `feishu:<account>:<scope>:<peer_id>`。

对齐 openclaw `extensions/feishu/src/conversation-id.ts`(MVP 简化):
- DM:`feishu:<account>:direct:<sender_open_id>` — 同一用户跨 chat 视作同一会话
  (与 openclaw 默认一致)
- 群聊:留 NotImplementedError 占位,接群聊时再加 4 种 scope
  (group / group+sender / group+topic / group+topic+sender)

这个 ID 同时充当 berry 侧 SessionStore 的 session_id key。
"""

from __future__ import annotations

from berry.channels.feishu.types import FeishuChatType, FeishuMessageEvent


def build_dm_conversation_id(account_id: str, sender_open_id: str) -> str:
    """`feishu:<account>:direct:<open_id>`"""
    return f"feishu:{account_id}:direct:{sender_open_id}"


def build_for_event(event: FeishuMessageEvent) -> str:
    """根据事件 chat_type 派生 conversation_id。"""
    if event.chat_type == FeishuChatType.P2P:
        return build_dm_conversation_id(event.account_id, event.sender_open_id)

    # 群聊 — MVP 不实现;调用方应该在 policy 阶段就拒掉
    raise NotImplementedError(
        f"group chat conversation_id 还未实现 (chat_type={event.chat_type})"
    )
