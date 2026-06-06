"""DM allowlist + 群聊准入策略 — MVP 只实现 DM 段。

对齐 openclaw `extensions/feishu/src/policy.ts`:
- ``dm_policy="open"``(默认)— 任何 sender 的 DM 都放行
- ``dm_policy="allowlist"`` — 只放行 ``allowed_open_ids`` 里的 sender
- 群聊先一律拒(MVP 不接,留给后续 group policy)

为什么把群聊接口预留:让 `bot.handle_feishu_message` 写起来不用改控制流 —
群聊事件直接调 `check_group_admission` 拿 False,后续把这个函数实现真就行。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from berry.channels.feishu.types import FeishuChatType, FeishuMessageEvent

DmPolicy = Literal["open", "allowlist"]


def check_dm_admission(
    sender_open_id: str,
    *,
    dm_policy: DmPolicy,
    allowed_open_ids: Iterable[str],
) -> bool:
    """是否允许 sender DM 机器人。

    - ``open``:任何非空 sender 都放行(对齐 openclaw default)
    - ``allowlist``:只放行 ``allowed_open_ids`` 里的 sender
    """
    sender_open_id = (sender_open_id or "").strip()
    if not sender_open_id:
        return False
    if dm_policy == "open":
        return True
    return sender_open_id in set(allowed_open_ids)


def check_group_admission(event: FeishuMessageEvent) -> bool:
    """群聊准入 — MVP 不接,直接 False。

    后续接群聊时实现:groupPolicy(open / allowlist / disabled)+
    requireMention + per-group allowFrom + per-group requireMention 覆盖。
    对应 openclaw `resolveFeishuGroupConversationIngressAccess` 一族。
    """
    return False


def admit(
    event: FeishuMessageEvent,
    *,
    dm_policy: DmPolicy,
    allowed_open_ids: Iterable[str],
) -> bool:
    """准入主入口 — `bot.handle_feishu_message` 调这一个就够。"""
    if event.chat_type == FeishuChatType.P2P:
        return check_dm_admission(
            event.sender_open_id,
            dm_policy=dm_policy,
            allowed_open_ids=allowed_open_ids,
        )
    return check_group_admission(event)
