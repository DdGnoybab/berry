"""单 account 监听器 — 装配 dispatcher / dedup / queue / WS client 后启动。

对齐 openclaw `extensions/feishu/src/monitor.account.ts` 的
`monitorSingleAccount` + `registerEventHandlers`(MVP 简化:只注册
`im.message.receive_v1`,其他事件类型留待后续):
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from berry.channels.feishu import client as client_mod
from berry.channels.feishu import monitor_state as state_mod
from berry.channels.feishu import policy as policy_mod
from berry.channels.feishu.card_action import handle_card_action
from berry.channels.feishu.dedup import FeishuDedup
from berry.channels.feishu.monitor_message import create_message_receive_handler
from berry.channels.feishu.monitor_transport import monitor_websocket
from berry.channels.feishu.sequential_queue import SequentialQueue
from berry.channels.feishu.types import ResolvedFeishuAccount
from berry.observability.logging import get_logger

logger = get_logger(__name__)


async def monitor_single_account(
    *,
    account: ResolvedFeishuAccount,
    state_dir: Path,
    dm_policy: policy_mod.DmPolicy,
    allowed_open_ids: list[str],
) -> None:
    """启动一个 account 的 WS 监听,跑到结束。"""
    account_id = account.account.account_id

    # 1. HTTP client → state(给 bot.handle 出站用)
    http_client = client_mod.create_http_client(account.account)
    state_mod.set_http_client(account_id, http_client)
    state_mod.set_resolved_account(account)

    # 2. dedup + queue (per-account 实例)
    dedup = FeishuDedup(namespace=account_id, state_dir=state_dir)
    queue = SequentialQueue()

    # 3. 拼 EventDispatcher,注册:
    #      - im.message.receive_v1     主消息流
    #      - card.action.trigger       审批卡片按钮回调
    loop = asyncio.get_running_loop()
    builder = client_mod.create_event_dispatcher_builder(account.account)
    handler = create_message_receive_handler(
        account=account,
        dedup=dedup,
        queue=queue,
        dm_policy=dm_policy,
        allowed_open_ids=allowed_open_ids,
        loop=loop,
    )

    def _card_action_handler(raw: object) -> object:
        # `raw` is lark's P2CardActionTrigger; closure captures account_id +
        # http_client so handle_card_action can patch the card.
        # MUST return the P2CardActionTriggerResponse — returning None makes
        # lark synthesize an empty response that Feishu treats as "revert
        # the card", undoing our update_card_by_message patch.
        return handle_card_action(http_client, raw, account_id=account_id)

    dispatcher = (
        builder
        .register_p2_im_message_receive_v1(handler)
        .register_p2_card_action_trigger(_card_action_handler)
        .build()
    )

    # 4. WS client + 阻塞跑
    ws_client = client_mod.create_feishu_ws_client(account.account, dispatcher)
    logger.info(
        "feishu_account_starting",
        account_id=account_id,
        bot_name=account.account.bot_name,
        dm_policy=dm_policy,
        allowlist_size=len(allowed_open_ids),
    )
    await monitor_websocket(account_id=account_id, ws_client=ws_client)
