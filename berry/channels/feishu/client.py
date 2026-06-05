"""lark-oapi 客户端工厂 — WS Client + HTTP Client + EventDispatcher。

对齐 openclaw `extensions/feishu/src/client.ts`:
- `create_feishu_ws_client(account, dispatcher)` → `lark_oapi.ws.Client`
- `create_event_dispatcher(account)` → `lark_oapi.EventDispatcherHandler` builder 起手
- `create_http_client(account)` → `lark_oapi.Client`(用于 `im.message.create` 等出站 API)

Reconnect:lark-oapi WS 自带 `auto_reconnect=True`,参数从飞书 server 配置读。
不在 berry 层手写 backoff 循环 — 沿用 SDK 是默认值(参考 berry CLAUDE.md)。
"""

from __future__ import annotations

import lark_oapi as lark
from lark_oapi.ws.client import Client as WsClient

from berry.channels.feishu.types import FeishuAccount


def create_http_client(account: FeishuAccount) -> lark.Client:
    """构造 lark HTTP Client(发消息、查 bot info 用)。

    HTTP Client 内部维护 access_token 缓存,不需要每次重建。
    """
    return (
        lark.Client.builder()
        .app_id(account.app_id)
        .app_secret(account.app_secret)
        .domain(account.domain)
        .build()
    )


def create_event_dispatcher_builder(
    account: FeishuAccount,
) -> lark.EventDispatcherHandler.builder:
    """返回 EventDispatcherHandlerBuilder 起手 — caller 链式 register_p2_xxx 注册 handler 后 .build()。

    encrypt_key / verification_token 在 WS 模式下其实 SDK 不强校验,但为了与
    webhook 模式同源,这里照传。
    """
    return lark.EventDispatcherHandler.builder(
        account.encrypt_key or "",
        account.verification_token or "",
    )


def create_feishu_ws_client(
    account: FeishuAccount,
    event_handler: lark.EventDispatcherHandler,
) -> WsClient:
    """构造长连 WS client,绑定一个已注册完 handler 的 EventDispatcher。

    返回值的 `.start()` 是同步阻塞调用(SDK 内 run_until_complete),
    上层(monitor_transport)负责把它放进 thread / 子 task 里跑。
    """
    return WsClient(
        app_id=account.app_id,
        app_secret=account.app_secret,
        event_handler=event_handler,
        domain=account.domain,
        auto_reconnect=True,
    )
