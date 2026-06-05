"""Feishu provider 入口 — 遍历多 account 并行启动各自的 WS 监听。

对齐 openclaw `extensions/feishu/src/monitor.ts` 的 `monitorFeishuProvider`。
MVP 实际只 1 个 account,但保留 list 入口,后续多账号不动 entrypoint。

Cancel/shutdown:asyncio.gather 会在第一个 task 抛错时把其他全 cancel。
进程层面交给 systemd / docker;不在应用层做 graceful shutdown(SDK 没暴露
clean disconnect API,硬退出比软退出可靠)。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from berry.channels.feishu.monitor_account import monitor_single_account
from berry.channels.feishu.types import ResolvedFeishuAccount
from berry.observability.logging import get_logger

logger = get_logger(__name__)


async def monitor_feishu_provider(
    accounts: Iterable[ResolvedFeishuAccount],
    *,
    state_dir: Path,
    allowed_open_ids: list[str],
) -> None:
    """对每个 account 起一个 task 跑 WS。任一 task 抛出就让进程崩,由进程
    管理器重启。"""
    accounts_list = list(accounts)
    if not accounts_list:
        logger.warning("feishu_no_accounts_configured")
        return

    logger.info(
        "feishu_provider_starting",
        account_count=len(accounts_list),
        state_dir=str(state_dir),
    )
    await asyncio.gather(
        *(
            monitor_single_account(
                account=acct,
                state_dir=state_dir,
                allowed_open_ids=allowed_open_ids,
            )
            for acct in accounts_list
        )
    )
