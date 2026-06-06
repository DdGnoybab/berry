"""DM allowlist + 群聊准入策略。

对齐 openclaw `extensions/feishu/src/policy.ts`(berry 简化版):
- ``dm_policy="open"``(默认)— 任何 sender 的 DM 都放行
- ``dm_policy="allowlist"`` — 只放行 ``allowed_open_ids`` 里的 sender
- 群聊白名单 ``group_allow_from``:只有列表内 chat_id 才响应
- 群聊唤醒条件:必须 @ bot(``bot_open_id`` 在 ``mentioned_open_ids`` 里)

berry 简化的部分(本期不实现,后续单独 PR):
- per-group sender allowlist(对应 openclaw `groupSenderAllowFrom`)
- topic / thread 会话作用域
- broadcast / dynamic agent
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


def check_group_admission(
    event: FeishuMessageEvent,
    *,
    group_allow_from: Iterable[str],
) -> bool:
    """群本身是否允许 berry 响应。chat_id 必须在 ``group_allow_from`` 里。

    空 ``group_allow_from`` = 禁用群聊。
    对齐 openclaw `resolveFeishuGroupConversationIngressAccess` 简化版:
    本期只看 chat_id 白名单,不实现 explicit-group / wildcard-group config。
    """
    if event.chat_type != FeishuChatType.GROUP:
        return False
    allow = {s.strip() for s in group_allow_from if s and s.strip()}
    if not allow:
        return False
    return event.chat_id in allow


def _check_bot_mentioned(
    event: FeishuMessageEvent, bot_open_id: str | None,
) -> bool:
    """是否在 mentioned_open_ids 里出现了 bot 自己的 open_id。

    bot_open_id 为空 → False(启动期没解出来,群聊保守拒)。
    对齐 openclaw `bot-content.ts::checkBotMentioned`(简化:只信赖 SDK
    mentions 数组,不再 fallback 文本里的 ``<at user_id="...">``)。
    """
    if not bot_open_id:
        return False
    return bot_open_id in event.mentioned_open_ids


def check_group_mention_required(
    event: FeishuMessageEvent,
    *,
    bot_open_id: str | None,
    require_mention: bool = True,
) -> bool:
    """已通过 chat 准入后,本条消息是否值得唤醒 LLM。

    - ``require_mention=True``(默认):必须 @ bot
    - ``require_mention=False``:每条都唤醒(预留接口,默认不开)

    ``bot_open_id`` 为空且 ``require_mention=True`` → 永远 False
    (启动期没解出来,保守拒)。
    """
    if not require_mention:
        return True
    return _check_bot_mentioned(event, bot_open_id)


def admit(
    event: FeishuMessageEvent,
    *,
    dm_policy: DmPolicy,
    allowed_open_ids: Iterable[str],
    bot_open_id: str | None = None,
    group_allow_from: Iterable[str] = (),
) -> bool:
    """准入主入口 — `bot.handle_feishu_message` 调这一个就够。

    DM:`check_dm_admission`;
    群聊:两层闸 — `check_group_admission`(chat 是否允许)
    + `check_group_mention_required`(本条是否唤醒)。

    对齐 openclaw `resolveFeishuGroupConversationIngressAccess` +
    `resolveFeishuGroupSenderActivationIngressAccess` 的两阶段思路。
    """
    if event.chat_type == FeishuChatType.P2P:
        return check_dm_admission(
            event.sender_open_id,
            dm_policy=dm_policy,
            allowed_open_ids=allowed_open_ids,
        )
    if event.chat_type == FeishuChatType.GROUP:
        if not check_group_admission(event, group_allow_from=group_allow_from):
            return False
        return check_group_mention_required(event, bot_open_id=bot_open_id)
    return False
