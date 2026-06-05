"""Outbound — 通过 lark HTTP Client 调用 `im.v1.message.create`。

对齐 openclaw `extensions/feishu/src/send.ts`(MVP 简化:不流式、不卡片
streaming):
- `send_text(client, chat_id, text)` — 纯文本(占位,bot.handle 错误兜底用)
- `send_card_markdown(client, chat_id, md)` — 单条卡片,markdown 内容

Card schema 用飞书最朴素的 div+markdown(template 也最简,不引入 CardKit
需要的 cardId 流程)。这是 MVP 取舍:能让 LLM 输出的 markdown 被渲染,但
不引入 streaming 复杂度。
"""

from __future__ import annotations

import json
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageResponse,
)

from berry.observability.logging import get_logger

logger = get_logger(__name__)


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


def send_text(
    client: lark.Client,
    *,
    chat_id: str,
    text: str,
) -> bool:
    """发纯文本到 chat_id。返回 True 表示 SDK 报告成功。

    失败只记日志,不 raise — 上层是 dispatcher 回调,raise 出去会污染
    sequential queue;让用户在飞书侧看不到回复 + 服务端日志能查就够。
    """
    try:
        resp = _create_message(
            client,
            receive_id=chat_id,
            receive_id_type="chat_id",
            msg_type="text",
            content=_build_text_content(text),
        )
    except Exception as exc:
        logger.error(
            "feishu_send_text_failed",
            chat_id=chat_id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return False
    if not resp.success():
        logger.error(
            "feishu_send_text_api_error",
            chat_id=chat_id,
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
) -> bool:
    """发 markdown 卡片到 chat_id。

    LLM 给的纯文本就是 markdown 输入(claude / deepseek 默认输出 md);
    所以「直接塞进卡片 element」就够。
    """
    content = _build_markdown_card(markdown, header_title=header_title)
    try:
        resp = _create_message(
            client,
            receive_id=chat_id,
            receive_id_type="chat_id",
            msg_type="interactive",
            content=content,
        )
    except Exception as exc:
        logger.error(
            "feishu_send_card_failed",
            chat_id=chat_id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return False
    if not resp.success():
        logger.error(
            "feishu_send_card_api_error",
            chat_id=chat_id,
            code=resp.code,
            msg=resp.msg,
        )
        return False
    return True
