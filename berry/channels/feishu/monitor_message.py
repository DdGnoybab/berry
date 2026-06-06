"""消息事件 handler 工厂 — `register_p2_im_message_receive_v1` 用。

对齐 openclaw `extensions/feishu/src/monitor.message-handler.ts`(MVP 简化:
不做 debounce):

    raw event → parse → dedup.seen ? drop : enqueue(handle_feishu_message)

为什么 dedup 在 enqueue 之前:dedup 是「这条事件之前是否处理过」的检查,
一定要在最早的位置做掉,避免空跑队列。

为什么调用方不直接传 raw event 给 handler — handler 是 EventDispatcher
注册的同步回调,它必须从某个 closure 取依赖。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from berry.channels.feishu import policy as policy_mod
from berry.channels.feishu import sequential_key as seq_key_mod
from berry.channels.feishu.bot import handle_feishu_message, parse_feishu_message_event
from berry.channels.feishu.dedup import FeishuDedup
from berry.channels.feishu.sequential_queue import SequentialQueue
from berry.channels.feishu.types import ResolvedFeishuAccount
from berry.observability.logging import get_logger

logger = get_logger(__name__)


def create_message_receive_handler(
    *,
    account: ResolvedFeishuAccount,
    dedup: FeishuDedup,
    queue: SequentialQueue,
    dm_policy: policy_mod.DmPolicy,
    allowed_open_ids: list[str],
    loop: asyncio.AbstractEventLoop,
) -> Callable[[P2ImMessageReceiveV1], None]:
    """返回一个供 `EventDispatcherHandlerBuilder.register_p2_im_message_receive_v1`
    注册的回调。

    Args:
        loop: 主 asyncio loop — handler 是 SDK 在 thread 里调的同步函数,
            必须把 async 工作 schedule 回主 loop。

    回调里只做最小工作:parse + dedup + enqueue,然后立刻返回(SDK 在等
    response 给飞书 server)。
    """
    account_id = account.account.account_id

    def _handler(raw: P2ImMessageReceiveV1) -> None:
        try:
            event = parse_feishu_message_event(account_id, raw)
        except Exception as exc:  # 防 SDK 给个怪 shape 让我们整体崩
            logger.error(
                "feishu_parse_failed",
                account_id=account_id,
                error_type=type(exc).__name__,
                error=str(exc),
                exc_info=True,
            )
            return
        if event is None:
            return

        if dedup.seen(event.message_id):
            logger.info(
                "feishu_dedup_hit",
                account_id=account_id,
                message_id=event.message_id,
            )
            return

        key = seq_key_mod.build_for_message(event)

        # SDK 回调跑在它自己的线程里;asyncio.create_task 必须在主 loop
        def _enqueue() -> None:
            queue.run(
                key,
                lambda: handle_feishu_message(
                    event,
                    dm_policy=dm_policy,
                    allowed_open_ids=allowed_open_ids,
                ),
            )

        loop.call_soon_threadsafe(_enqueue)

    return _handler
