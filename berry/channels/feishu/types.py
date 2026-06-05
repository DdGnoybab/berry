"""Feishu channel domain types.

对齐 openclaw `extensions/feishu/src/types.ts` + 散落在各文件的 type 定义。
不引 lark-oapi 类型,避免业务代码绑死 SDK。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class FeishuChatType(StrEnum):
    """飞书聊天类型。

    SDK 事件 `event.message.chat_type` 给的就是这两个字符串。
    """

    P2P = "p2p"      # DM
    GROUP = "group"  # 群聊(MVP 不处理)


@dataclass(frozen=True)
class FeishuAccount:
    """飞书 app 凭证 + 业务标记 — env 读完直接落进这个 dataclass。"""

    account_id: str       # 业务侧标识(用作 dedup namespace、日志 key);默认用 app_id
    app_id: str
    app_secret: str
    domain: str = "https://open.feishu.cn"
    encrypt_key: str | None = None
    verification_token: str | None = None
    bot_name: str = "berry"


@dataclass(frozen=True)
class ResolvedFeishuAccount:
    """启动时把 bot 自身身份补全后的 account。

    `bot_open_id` 在启动后通过调用 `auth/v3/app_access_token` + 之后的 bot info
    解出来,用于:1) 群聊里识别哪条 mention 指向 bot 自己;2) 自己发出的消息
    在收到回声时直接 dedup。MVP 阶段只 DM,但解出来记日志能省排查时间。
    """

    account: FeishuAccount
    bot_open_id: str | None = None


@dataclass(frozen=True)
class FeishuMessageEvent:
    """`im.message.receive_v1` 解析后的归一化事件 — channel 业务代码看到的样子。

    刻意不带 SDK 原始对象,只留必要字段;后续要加群聊 / 卡片 action,
    再扩这个 dataclass。
    """

    account_id: str
    message_id: str
    chat_id: str
    chat_type: FeishuChatType
    sender_open_id: str
    text: str                   # 已经从 content JSON 里抽出来的纯文本 + 已剥 @mention
    mentioned_open_ids: list[str] = field(default_factory=list)  # 提及到的 open_id 列表(MVP 不用,但 parse 出来不亏)
    create_time_ms: int | None = None
