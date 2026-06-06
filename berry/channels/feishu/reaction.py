"""飞书消息表情回复（Reaction）— 收到消息时加 Typing 表情,回复后移除。

对齐 openclaw `extensions/feishu/src/typing.ts` + `reactions.ts`:
- `add_typing_reaction(client, message_id)` → 返回 reaction_id
- `remove_reaction(client, message_id, reaction_id)`

用法:bot.py 在 `handle_feishu_message` 开头加表情,回复完(或出错)移除。
失败不阻塞主流程 — 只记 warning 日志。
"""

from __future__ import annotations

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageReactionRequest,
    CreateMessageReactionRequestBody,
    CreateMessageReactionResponse,
    DeleteMessageReactionRequest,
    DeleteMessageReactionResponse,
    Emoji,
)

from berry.observability.logging import get_logger

logger = get_logger(__name__)

TYPING_EMOJI = "Typing"


def add_typing_reaction(client: lark.Client, message_id: str) -> str | None:
    """给消息加 Typing 表情,返回 reaction_id(失败返回 None)。"""
    request = (
        CreateMessageReactionRequest.builder()
        .message_id(message_id)
        .request_body(
            CreateMessageReactionRequestBody.builder()
            .reaction_type(Emoji.builder().emoji_type(TYPING_EMOJI).build())
            .build()
        )
        .build()
    )
    try:
        resp: CreateMessageReactionResponse = client.im.v1.message_reaction.create(request)
        if not resp.success():
            logger.warning(
                "feishu_add_reaction_failed",
                code=resp.code,
                msg=resp.msg,
                message_id=message_id,
            )
            return None
        return resp.data.reaction_id if resp.data else None
    except Exception as exc:
        logger.warning(
            "feishu_add_reaction_error",
            error_type=type(exc).__name__,
            error=str(exc),
            message_id=message_id,
        )
        return None


def remove_reaction(client: lark.Client, message_id: str, reaction_id: str) -> None:
    """移除一条表情回复。失败只记日志,不 raise。"""
    request = (
        DeleteMessageReactionRequest.builder()
        .message_id(message_id)
        .reaction_id(reaction_id)
        .build()
    )
    try:
        resp: DeleteMessageReactionResponse = client.im.v1.message_reaction.delete(request)
        if not resp.success():
            logger.warning(
                "feishu_remove_reaction_failed",
                code=resp.code,
                msg=resp.msg,
                message_id=message_id,
                reaction_id=reaction_id,
            )
    except Exception as exc:
        logger.warning(
            "feishu_remove_reaction_error",
            error_type=type(exc).__name__,
            error=str(exc),
            message_id=message_id,
            reaction_id=reaction_id,
        )
