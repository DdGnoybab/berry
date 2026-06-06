"""Feishu entrypoint — 启动 lark-oapi WS 长连,把消息接到 ConversationRuntime。

启动顺序:
  1. 加载 .env / Settings + FeishuSettings
  2. seed default user(MVP 单用户,跟 CLI 共用同一个 default user)
  3. 构造 ConversationRuntime + system prompt(复用 CLI 同款装配)
  4. 包装 _CliTurnRunner 为 TurnRunner,塞进 FeishuRuntimeAdapter
  5. set_feishu_runtime(adapter)
  6. monitor_feishu_provider([account])

跑法:
  uv run python -m berry.entrypoints.feishu

退出:Ctrl-C 或进程被 kill;不做 graceful shutdown(SDK 没暴露 disconnect)。

为什么不复用 entrypoints/cli.py 的 MethodRegistry / configure_runner 那套:
飞书 channel 直接面向用户消息,不需要 RPC method 抽象;走那套会增加无谓
绕路 + 跨 transport 的 ctx 字段污染。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import UUID

from berry.channels.feishu import client as client_mod
from berry.channels.feishu.approval_channel import FeishuApprovalChannel
from berry.channels.feishu.monitor import monitor_feishu_provider
from berry.channels.feishu.runtime import set_feishu_runtime
from berry.channels.feishu.runtime_adapter import FeishuRuntimeAdapter
from berry.channels.feishu.types import FeishuAccount, ResolvedFeishuAccount
from berry.config import FeishuSettings
from berry.core.db.repos.user_repo import UserRepo
from berry.core.db.session import async_session_factory, engine

# 复用 CLI 的 ConversationRuntime 装配 — 它已经把 LLM gateway / tool registry /
# system prompt 都拼好了,飞书直接拿来用,行为一致(同一个 berry agent)。
from berry.entrypoints.cli import _build_runtime, _CliTurnRunner
from berry.observability.logging import configure_logging, get_logger

logger = get_logger(__name__)

DEFAULT_USER_HANDLE = "default"
DEFAULT_STATE_DIR = Path.home() / ".berry"


async def _seed_user() -> UUID:
    async with async_session_factory() as db:
        user = await UserRepo(db).get_or_create_by_handle(
            handle=DEFAULT_USER_HANDLE,
            display_name="Default User",
        )
        return user.id


def _resolve_state_dir() -> Path:
    """`BERRY_STATE_DIR` env 覆盖,默认 ~/.berry。"""
    override = os.environ.get("BERRY_STATE_DIR")
    return Path(override).expanduser() if override else DEFAULT_STATE_DIR


def _build_account(s: FeishuSettings) -> ResolvedFeishuAccount:
    if not s.enabled:
        raise RuntimeError(
            "Feishu 凭证缺失:请在 .env 设置 FEISHU_APP_ID + FEISHU_APP_SECRET"
        )
    acct = FeishuAccount(
        account_id=s.app_id,            # MVP:用 app_id 作为业务 id
        app_id=s.app_id,
        app_secret=s.app_secret.get_secret_value(),
        domain=s.domain,
        encrypt_key=s.encrypt_key.get_secret_value() if s.encrypt_key else None,
        verification_token=s.verification_token.get_secret_value() or None,
        bot_name=s.bot_name,
    )
    # MVP 不去解 bot_open_id(那是给 mention gating 用的,DM 用不到)
    return ResolvedFeishuAccount(account=acct, bot_open_id=None)


async def _async_main() -> None:
    log_format = os.environ.get("LOG_FORMAT", "console")
    configure_logging(log_format=log_format)

    feishu_settings = FeishuSettings()
    if not feishu_settings.enabled:
        logger.error("feishu_credentials_missing")
        return

    if (
        feishu_settings.dm_policy == "allowlist"
        and not feishu_settings.allowed_open_ids
    ):
        logger.warning(
            "feishu_allowlist_empty",
            note=(
                "FEISHU_DM_POLICY=allowlist 但 FEISHU_ALLOWED_OPEN_IDS 为空 "
                "— 所有 DM 都会被拒绝。把你自己的 open_id 加进 .env,或者把 "
                "FEISHU_DM_POLICY 改成 open(默认)。"
            ),
        )

    state_dir = _resolve_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)

    user_id = await _seed_user()

    # Wire FeishuApprovalChannel before _build_runtime so the runtime is built
    # with it. ChatResolver is post-injected once the adapter exists (the
    # adapter -> runner -> runtime -> channel chain would otherwise loop).
    account = _build_account(feishu_settings)
    lark_client = client_mod.create_http_client(account.account)
    approval_channel = FeishuApprovalChannel(client=lark_client)

    runtime, system_prompt = _build_runtime(approval_channel=approval_channel)
    runner = _CliTurnRunner(runtime, system_prompt)

    adapter = FeishuRuntimeAdapter(
        runner=runner,
        state_dir=state_dir,
        default_user_id=user_id,
    )
    approval_channel.set_chat_resolver(adapter.chat_resolver)
    set_feishu_runtime(adapter)

    logger.info(
        "feishu_entrypoint_starting",
        app_id=account.account.app_id,
        bot_name=account.account.bot_name,
        state_dir=str(state_dir),
        dm_policy=feishu_settings.dm_policy,
        allowlist_size=len(feishu_settings.allowed_open_ids),
        user_id=str(user_id),
    )

    try:
        await monitor_feishu_provider(
            [account],
            state_dir=state_dir,
            dm_policy=feishu_settings.dm_policy,
            allowed_open_ids=list(feishu_settings.allowed_open_ids),
        )
    finally:
        await engine.dispose()


def main() -> None:
    """同步入口。"""
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("feishu_entrypoint_interrupted")


if __name__ == "__main__":
    main()
