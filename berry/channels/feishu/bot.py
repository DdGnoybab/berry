"""主编排:把一条飞书事件 → AgentEvent stream → outbound 卡片。

对齐 openclaw `extensions/feishu/src/bot.ts`(MVP 简化版):
- `parse_feishu_message_event(raw)` — SDK 事件 → 归一化 dataclass
- `handle_feishu_message(event, context)` — 主流程,每个事件跑一次

不做的:
- 群聊处理(policy.admit 直接拒)
- streaming card
- 审批卡片
- @mention 解析(MVP DM 用不到,但留了 mention.id.open_id 抽取代码)

外部依赖通过参数注入,不直接 import singleton:
- HTTP client 由 `monitor_state.get_http_client(account_id)` 取
- runtime adapter 由 `runtime.get_feishu_runtime()` 取
- allowlist 由 caller 传入

调用方:`monitor_message.create_message_receive_handler` 在解事件 + dedup +
入队后,在 sequential queue 内部把 event 喂给 `handle_feishu_message`。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from berry.channels.feishu import conversation_id as conv_id_mod
from berry.channels.feishu import policy as policy_mod
from berry.channels.feishu import send as send_mod
from berry.channels.feishu.monitor_state import get_http_client
from berry.channels.feishu.runtime import get_feishu_runtime
from berry.channels.feishu.types import (
    FeishuChatType,
    FeishuMessageEvent,
)
from berry.observability.logging import get_logger

logger = get_logger(__name__)


# ---- parse -----------------------------------------------------------------


def parse_feishu_message_event(
    account_id: str,
    raw: P2ImMessageReceiveV1,
) -> FeishuMessageEvent | None:
    """SDK 事件 → 归一化 FeishuMessageEvent。返回 None 表示事件无效 / 缺字段,
    上层应直接丢弃。

    关键解析步骤:
    1. 取 message_id / chat_id / chat_type / sender open_id
    2. 解 content JSON,从 `text` / `post` 类型抽出文本(MVP 只支持 text;
       post 等富文本暂落字符串化版本)
    3. 剥 @mention(MVP DM 不用,但留 hooks)
    """
    if raw.event is None or raw.event.message is None or raw.event.sender is None:
        return None

    msg = raw.event.message
    sender = raw.event.sender

    if not msg.message_id or not msg.chat_id:
        return None

    sender_open_id = (sender.sender_id.open_id if sender.sender_id else "") or ""
    if not sender_open_id:
        return None

    try:
        chat_type = FeishuChatType(msg.chat_type or "")
    except ValueError:
        # 未知 chat_type — 当作不响应
        logger.warning(
            "feishu_unknown_chat_type",
            chat_type=msg.chat_type,
            account_id=account_id,
        )
        return None

    text = _extract_text(msg.message_type, msg.content)
    mentioned: list[str] = []
    if msg.mentions:
        for m in msg.mentions:
            if m and m.id and m.id.open_id:
                mentioned.append(m.id.open_id)

    text_stripped = _strip_mentions_from_text(text, msg.mentions or [])

    return FeishuMessageEvent(
        account_id=account_id,
        message_id=msg.message_id,
        chat_id=msg.chat_id,
        chat_type=chat_type,
        sender_open_id=sender_open_id,
        text=text_stripped,
        mentioned_open_ids=mentioned,
        create_time_ms=int(msg.create_time) if msg.create_time else None,
    )


def _extract_text(msg_type: str | None, raw_content: str | None) -> str:
    """从飞书消息 content JSON 抽文本。MVP 只完整支持 type=text,其他类型
    退化成空串(让上层决定要不要回应)。"""
    if not raw_content:
        return ""
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return ""

    if msg_type == "text":
        return (payload.get("text") or "").strip()
    if msg_type == "post":
        # 富文本:把 paragraphs.text 拼起来
        title = payload.get("title") or ""
        parts: list[str] = []
        for line in payload.get("content") or []:
            for seg in line or []:
                if isinstance(seg, dict) and seg.get("tag") == "text":
                    parts.append(seg.get("text") or "")
        body = "".join(parts).strip()
        return f"{title}\n{body}".strip() if title else body
    # 其他类型(image/file/audio…) — MVP 不接
    return ""


def _strip_mentions_from_text(text: str, mentions: Iterable[object]) -> str:
    """飞书 text 内 @ 用 `@_user_1` 这种 placeholder,真实信息在 mentions 数组。
    剥掉 placeholder,只保留正文 — 与 openclaw `normalizeMentions` 同款。

    Note:
        MVP DM 没 @,但保留这个 helper 让接群聊时只改 caller。
    """
    if not text:
        return ""
    out = text
    for m in mentions:
        key = getattr(m, "key", None)
        if isinstance(key, str) and key:
            out = out.replace(key, "")
    return out.strip()


# ---- main orchestration ---------------------------------------------------


async def handle_feishu_message(
    event: FeishuMessageEvent,
    *,
    dm_policy: policy_mod.DmPolicy,
    allowed_open_ids: list[str],
) -> None:
    """主流程:policy → conversation_id → run_turn → 发卡片。

    每条进入这里的事件都已经 dedup + 在 sequential queue 内部跑了。
    出错只记日志 + 给用户回个错误提示文本,不 raise(raise 会污染队列链)。
    """
    log = logger.bind(
        account_id=event.account_id,
        chat_id=event.chat_id,
        sender_open_id=event.sender_open_id,
        message_id=event.message_id,
    )
    log.info("feishu_message_received")

    # 1. 准入
    if not policy_mod.admit(
        event, dm_policy=dm_policy, allowed_open_ids=allowed_open_ids,
    ):
        log.info("feishu_allowlist_block", dm_policy=dm_policy)
        return

    # 2. conversation_id
    try:
        conversation_id = conv_id_mod.build_for_event(event)
    except NotImplementedError:
        log.warning("feishu_chat_type_unsupported", chat_type=event.chat_type)
        return

    if not event.text:
        log.info("feishu_empty_text_dropped")
        return

    log = log.bind(conversation_id=conversation_id)
    log.info("feishu_turn_started")

    # 3. 跑 LLM
    adapter = get_feishu_runtime()
    try:
        final_text = await adapter.run_turn(
            conversation_id,
            event.text,
            chat_id=event.chat_id,
            user_open_id=event.sender_open_id,
        )
    except Exception as exc:
        # adapter 自己应该兜底返回错误文本;这里再加一道防线
        log.error(
            "feishu_runtime_unhandled_exception",
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        final_text = f"berry 出错了:{type(exc).__name__}"

    log.info("feishu_turn_completed", final_text_chars=len(final_text))

    # 4. 出站
    client = get_http_client(event.account_id)
    ok = send_mod.send_card_markdown(
        client,
        chat_id=event.chat_id,
        markdown=final_text,
    )
    if not ok:
        # 卡片失败兜底纯文本(罕见,但万一卡片 schema 抽风)
        send_mod.send_text(client, chat_id=event.chat_id, text=final_text)


# ---- testing helpers ------------------------------------------------------


def _force_bot_open_id(event: FeishuMessageEvent, bot_open_id: str) -> FeishuMessageEvent:
    """测试用 — 强制把 mentioned_open_ids 加上 bot 自己。"""
    return replace(event, mentioned_open_ids=[*event.mentioned_open_ids, bot_open_id])
