"""DM allowlist + 群聊准入策略 — MVP 只实现 DM 段。

对齐 openclaw `extensions/feishu/src/policy.ts`(MVP 简化):
- `check_dm_admission(sender_open_id, allowed) -> bool` — 只 DM 用
- 群聊相关函数留架(签名 + NotImplementedError),满足 spec §11 trade-off
  「后续要做时改什么」清单可见

为什么把群聊接口预留:让 `bot.handle_feishu_message` 写起来不用改控制流 —
群聊事件直接调 `check_group_admission` 拿 False,后续把这个函数实现真就行。
"""

from __future__ import annotations

from collections.abc import Iterable

from berry.channels.feishu.types import FeishuChatType, FeishuMessageEvent


def check_dm_admission(
    sender_open_id: str,
    allowed_open_ids: Iterable[str],
) -> bool:
    """是否允许 sender DM 机器人。

    空 allowlist = 拒绝所有(MVP 严格模式;openclaw 里 `dmPolicy=allowlist`
    且 `allowFrom=[]` 也是拒所有)。
    """
    sender_open_id = (sender_open_id or "").strip()
    if not sender_open_id:
        return False
    return sender_open_id in set(allowed_open_ids)


def check_group_admission(event: FeishuMessageEvent) -> bool:  # noqa: ARG001
    """群聊准入 — MVP 不接,直接 False。

    后续接群聊时实现:groupPolicy(open / allowlist / disabled)+
    requireMention + per-group allowFrom + per-group requireMention 覆盖。
    对应 openclaw `resolveFeishuGroupConversationIngressAccess` 一族。
    """
    return False


def admit(
    event: FeishuMessageEvent,
    *,
    allowed_open_ids: Iterable[str],
) -> bool:
    """准入主入口 — `bot.handle_feishu_message` 调这一个就够。"""
    if event.chat_type == FeishuChatType.P2P:
        return check_dm_admission(event.sender_open_id, allowed_open_ids)
    return check_group_admission(event)
