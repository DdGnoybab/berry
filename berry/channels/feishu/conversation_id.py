"""Conversation ID 构造 — `feishu:<account>:<scope>:<peer_id>`。

对齐 openclaw `extensions/feishu/src/conversation-id.ts`:
- DM:`feishu:<account>:direct:<sender_open_id>` — 同一用户跨 chat 视作同一会话
  (与 openclaw 默认一致)
- 群聊:`feishu:<account>:group:<chat_id>` — 全群共享一个 session
  (对应 openclaw `groupSessionScope="group"` 默认值)

本期不实现的 scope(后续按需 PR):
- `group_sender`        — 群里每人独立会话
- `group_topic`         — 话题群每个话题独立会话
- `group_topic_sender`  — 话题群每人每话题独立

这个 ID 同时充当 berry 侧 SessionStore 的 session_id key。
"""

from __future__ import annotations

from berry.channels.feishu.types import FeishuChatType, FeishuMessageEvent


def build_dm_conversation_id(account_id: str, sender_open_id: str) -> str:
    """`feishu:<account>:direct:<open_id>`"""
    return f"feishu:{account_id}:direct:{sender_open_id}"


def build_group_conversation_id(account_id: str, chat_id: str) -> str:
    """`feishu:<account>:group:<chat_id>` — 全群共享一个 session。"""
    return f"feishu:{account_id}:group:{chat_id}"


def build_for_event(event: FeishuMessageEvent) -> str:
    """根据事件 chat_type 派生 conversation_id。"""
    if event.chat_type == FeishuChatType.P2P:
        return build_dm_conversation_id(event.account_id, event.sender_open_id)
    if event.chat_type == FeishuChatType.GROUP:
        return build_group_conversation_id(event.account_id, event.chat_id)
    raise NotImplementedError(
        f"unsupported chat_type for conversation_id: {event.chat_type}"
    )
