"""Outbound — 通过 lark HTTP Client 调用 `im.v1.message.create` / `.patch`。

对齐 openclaw `extensions/feishu/src/send.ts`:
- `send_text(client, chat_id, text)` — 纯文本(bot.handle 错误兜底用)
- `send_card_markdown(client, chat_id, md)` — 单条 markdown 卡片(主回复用)
- `send_approval_card(client, chat_id, card_json)` — 审批用 interactive 卡片
- `update_card_by_message(client, message_id, card_json)` — 卡片确认后改成
  immutable 的「已允许 / 已拒绝 / 超时」态
- `send_invalid_notice(client, chat_id, reason)` — 卡片校验失败时给用户
  发一段中文提示,对齐 openclaw `sendInvalidInteractionNotice`

Card schema 用飞书最朴素的 div+markdown(主回复) + CardKit v2(审批),
不接 streaming card(那是另一个分支的事)。
"""

from __future__ import annotations

import json
from typing import Any, Literal

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
    PatchMessageRequest,
    PatchMessageRequestBody,
    PatchMessageResponse,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    ReplyMessageResponse,
)

from berry.observability.logging import get_logger

logger = get_logger(__name__)

InvalidNoticeReason = Literal[
    "malformed", "stale", "wrong_user", "wrong_conversation",
]


def _build_text_content(text: str) -> str:
    return json.dumps({"text": text}, ensure_ascii=False)


def _build_markdown_card(md: str, *, header_title: str | None = None) -> str:
    """飞书 card v1 schema(够 markdown 渲染)。

    模板 schema 见
    https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/feishu-cards/card-json-structure
    用最小集:`config.wide_screen_mode=True` + `elements: [{tag: 'markdown', content}]`。
    """
    card: dict[str, Any] = {
        "config": {"wide_screen_mode": True},
        "elements": [
            {
                "tag": "markdown",
                "content": md,
            }
        ],
    }
    if header_title is not None:
        card["header"] = {
            "title": {"tag": "plain_text", "content": header_title},
        }
    return json.dumps(card, ensure_ascii=False)


def _create_message(
    client: lark.Client,
    *,
    receive_id: str,
    receive_id_type: str,
    msg_type: str,
    content: str,
) -> CreateMessageResponse:
    """同步 HTTP 调用。lark-oapi 的 sync 接口在 SDK 内部用 requests。"""
    body = (
        CreateMessageRequestBody.builder()
        .receive_id(receive_id)
        .msg_type(msg_type)
        .content(content)
        .build()
    )
    req = (
        CreateMessageRequest.builder()
        .receive_id_type(receive_id_type)
        .request_body(body)
        .build()
    )
    return client.im.v1.message.create(req)


def _reply_message(
    client: lark.Client,
    *,
    message_id: str,
    msg_type: str,
    content: str,
    reply_in_thread: bool = False,
) -> ReplyMessageResponse:
    """走飞书 `POST /open-apis/im/v1/messages/:message_id/reply`。

    群聊出站用,挂在触发消息下面;``reply_in_thread=False`` 让回复留在主聊天
    视图,避免被推进 topic thread。
    """
    body = (
        ReplyMessageRequestBody.builder()
        .msg_type(msg_type)
        .content(content)
        .reply_in_thread(reply_in_thread)
        .build()
    )
    req = (
        ReplyMessageRequest.builder()
        .message_id(message_id)
        .request_body(body)
        .build()
    )
    return client.im.v1.message.reply(req)


def send_text(
    client: lark.Client,
    *,
    chat_id: str,
    text: str,
    reply_to_message_id: str | None = None,
) -> bool:
    """发纯文本到 chat_id。返回 True 表示 SDK 报告成功。

    失败只记日志,不 raise — 上层是 dispatcher 回调,raise 出去会污染
    sequential queue;让用户在飞书侧看不到回复 + 服务端日志能查就够。

    Args:
        reply_to_message_id: 非空时走 reply API,把消息挂在原消息下面
            (群聊形态);None 走 create API(DM 形态)。
    """
    content = _build_text_content(text)
    try:
        if reply_to_message_id is None:
            resp: CreateMessageResponse | ReplyMessageResponse = _create_message(
                client,
                receive_id=chat_id,
                receive_id_type="chat_id",
                msg_type="text",
                content=content,
            )
        else:
            resp = _reply_message(
                client,
                message_id=reply_to_message_id,
                msg_type="text",
                content=content,
            )
    except Exception as exc:
        logger.error(
            "feishu_send_text_failed",
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return False
    if not resp.success():
        logger.error(
            "feishu_send_text_api_error",
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            code=resp.code,
            msg=resp.msg,
        )
        return False
    return True


def send_card_markdown(
    client: lark.Client,
    *,
    chat_id: str,
    markdown: str,
    header_title: str | None = "berry",
    reply_to_message_id: str | None = None,
) -> bool:
    """发 markdown 卡片到 chat_id。

    LLM 给的纯文本就是 markdown 输入(claude / deepseek 默认输出 md);
    所以「直接塞进卡片 element」就够。

    Args:
        reply_to_message_id: 非空时 reply 到原消息(群聊形态);
            None 走 create(DM 形态)。
    """
    content = _build_markdown_card(markdown, header_title=header_title)
    try:
        if reply_to_message_id is None:
            resp: CreateMessageResponse | ReplyMessageResponse = _create_message(
                client,
                receive_id=chat_id,
                receive_id_type="chat_id",
                msg_type="interactive",
                content=content,
            )
        else:
            resp = _reply_message(
                client,
                message_id=reply_to_message_id,
                msg_type="interactive",
                content=content,
            )
    except Exception as exc:
        logger.error(
            "feishu_send_card_failed",
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return False
    if not resp.success():
        logger.error(
            "feishu_send_card_api_error",
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            code=resp.code,
            msg=resp.msg,
        )
        return False
    return True


def send_approval_card(
    client: lark.Client,
    *,
    chat_id: str,
    card_json: str,
    reply_to_message_id: str | None = None,
) -> str | None:
    """Send a pre-built interactive card. Returns the new ``message_id`` so the
    caller can later patch the card to a resolved state. None on failure.

    ``card_json`` is the full Feishu card content string (typically built by
    ``card_ux_approval.build_approval_card``).

    Args:
        reply_to_message_id: 非空时 reply 到触发消息(群聊形态),让卡片紧
            跟用户的 @ 触发;None 走 create(DM 形态)。
    """
    try:
        if reply_to_message_id is None:
            resp: CreateMessageResponse | ReplyMessageResponse = _create_message(
                client,
                receive_id=chat_id,
                receive_id_type="chat_id",
                msg_type="interactive",
                content=card_json,
            )
        else:
            resp = _reply_message(
                client,
                message_id=reply_to_message_id,
                msg_type="interactive",
                content=card_json,
            )
    except Exception as exc:
        logger.error(
            "feishu_send_approval_card_failed",
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return None
    if not resp.success():
        logger.error(
            "feishu_send_approval_card_api_error",
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
            code=resp.code,
            msg=resp.msg,
        )
        return None
    if resp.data is None or not resp.data.message_id:
        logger.error(
            "feishu_send_approval_card_missing_message_id",
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
        )
        return None
    return resp.data.message_id


def update_card_by_message(
    client: lark.Client,
    *,
    message_id: str,
    card_json: str,
) -> bool:
    """Patch an existing interactive card. Used to flip the approval card
    from pending → allowed/denied/timeout immutable state.
    """
    body = PatchMessageRequestBody.builder().content(card_json).build()
    req = (
        PatchMessageRequest.builder()
        .message_id(message_id)
        .request_body(body)
        .build()
    )
    try:
        resp: PatchMessageResponse = client.im.v1.message.patch(req)
    except Exception as exc:
        logger.error(
            "feishu_patch_card_failed",
            message_id=message_id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return False
    if not resp.success():
        logger.error(
            "feishu_patch_card_api_error",
            message_id=message_id,
            code=resp.code,
            msg=resp.msg,
        )
        return False
    return True


_INVALID_NOTICE_TEXT: dict[InvalidNoticeReason, str] = {
    "malformed":          "卡片操作无效。",
    "stale":              "卡片已过期,请重新触发。",
    "wrong_user":         "这张卡片属于其他用户。",
    "wrong_conversation": "这张卡片属于其他会话。",
}


def send_invalid_notice(
    client: lark.Client,
    *,
    chat_id: str,
    reason: InvalidNoticeReason,
    reply_to_message_id: str | None = None,
) -> bool:
    """Send a plain-text notice when a card_action validation fails.

    Mirrors openclaw ``sendInvalidInteractionNotice``: a 1-line warning that
    explains why the click was rejected so the user knows whether to retry
    or wait.

    Args:
        reply_to_message_id: 非空时 reply 到错卡片(群聊里点错卡时让提示
            紧跟错卡,不污染主线)。
    """
    text = _INVALID_NOTICE_TEXT[reason]
    return send_text(
        client,
        chat_id=chat_id,
        text=f"⚠️ {text}",
        reply_to_message_id=reply_to_message_id,
    )
