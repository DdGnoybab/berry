"""WebSocket transport — 启动 lark-oapi WSClient 并跑到进程退出。

对齐 openclaw `extensions/feishu/src/monitor.transport.ts` 的 `monitorWebSocket`,
但实现路径不一样:
- openclaw 用 Node 的 lark sdk,reconnect / backoff 全在 sdk 内部
- berry 用 lark-oapi (Python),sdk 自带 `auto_reconnect=True` + 自适应间隔
- 所以 berry 这一层是个 thin shim:把 SDK 的 `start()`(同步阻塞)放进
  `asyncio.to_thread`,让我们 `await` 时不卡住事件循环

如果 SDK reconnect 失败到底层 raise 出来,就让进程退出 — 由进程管理器
(systemd / docker restart)兜底重启;比在应用层乱搞 backoff 干净。
"""

from __future__ import annotations

import asyncio

from lark_oapi.ws.client import Client as WsClient

from berry.observability.logging import get_logger

logger = get_logger(__name__)


async def monitor_websocket(
    *,
    account_id: str,
    ws_client: WsClient,
) -> None:
    """阻塞等 WS client 跑到结束(理论上不会结束,除非 SDK 抛出来)。

    Note:
        `ws_client.start()` 内部 `loop.run_until_complete(...)`,我们必须
        在独立线程里跑,否则会跟当前 asyncio loop 打架。
    """
    logger.info("feishu_ws_starting", account_id=account_id)
    try:
        await asyncio.to_thread(ws_client.start)
    except Exception as exc:
        logger.error(
            "feishu_ws_terminated",
            account_id=account_id,
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        raise
    logger.warning("feishu_ws_returned", account_id=account_id)
