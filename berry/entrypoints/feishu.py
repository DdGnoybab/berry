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
from berry.channels.feishu.todo_card import render_todo_card
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


def _resolve_workspace_path() -> Path | None:
    """Resolve the learning workspace.

    Resolution order:
      1. ``BERRY_LEARNING_WORKSPACE`` env var (explicit override)
      2. cwd — same convention as claw-code's ``cd <project> && claw``

    Disabled when cwd is the berry repo itself (detected via the presence of
    ``berry/__init__.py``) — running ``uv run berry-feishu`` from inside the
    berry source tree shouldn't accidentally turn berry's own checkout into
    a learning workspace.

    Local mode: user ``cd ~/learning/redis`` then runs berry-feishu.
    Cloud mode (MVP): operator deploys with ``BERRY_LEARNING_WORKSPACE``
    pointing at the per-deploy workspace dir; multi-user / per-topic
    isolation is a V2 concern (see ``docs/berry-L-design.md``).
    """
    override = os.environ.get("BERRY_LEARNING_WORKSPACE")
    if override:
        p = Path(override).expanduser()
        if not p.is_dir():
            logger.warning(
                "feishu_learning_workspace_missing",
                path=str(p),
                note="BERRY_LEARNING_WORKSPACE points at a non-existent dir; learning skill disabled.",
            )
            return None
        return p

    cwd = Path.cwd()
    if (cwd / "berry" / "__init__.py").is_file() and (cwd / "pyproject.toml").is_file():
        logger.info(
            "feishu_learning_workspace_skipped_repo_root",
            cwd=str(cwd),
            note="cwd looks like the berry repo itself; learning skill disabled. cd into a learning workspace, or set BERRY_LEARNING_WORKSPACE.",
        )
        return None
    return cwd


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
    # bot_open_id 来自 .env;空时群聊整体禁用,DM 不受影响。
    # 启动期不做 contact API 自动解析(后续按需 PR)。
    return ResolvedFeishuAccount(
        account=acct,
        bot_open_id=s.bot_open_id or None,
    )


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

    # 群聊配置健全性提示 — 帮用户排查「群里 @ 没反应」类问题
    if feishu_settings.group_allow_from and not feishu_settings.bot_open_id:
        logger.warning(
            "feishu_group_bot_open_id_missing",
            note=(
                "FEISHU_GROUP_ALLOW_FROM 已配置但 FEISHU_BOT_OPEN_ID 为空 — "
                "群聊 @ bot 检测拿不到 bot 自身 ID,所有群聊消息会被拒。"
                "请把 bot 的 open_id 填进 FEISHU_BOT_OPEN_ID。"
            ),
        )
    if feishu_settings.bot_open_id and not feishu_settings.group_allow_from:
        logger.info(
            "feishu_group_allow_from_empty",
            note=(
                "FEISHU_BOT_OPEN_ID 已配但 FEISHU_GROUP_ALLOW_FROM 为空 — "
                "群聊禁用,只 DM 工作。把目标群的 chat_id 加进 "
                "FEISHU_GROUP_ALLOW_FROM 即可启用群聊。"
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

    workspace_path = _resolve_workspace_path()

    # Initialize the learning workspace before building the runtime so that
    # the LLM's first turn can already read LEARNER.md / progress.json /
    # ROADMAP.md. Also syncs the packaged SKILL.md to ~/.berry/skills/learning/
    # so the `skill` tool can resolve `skill="learning"`.
    if workspace_path is not None:
        from berry.skills.learning.init_workspace import init_learning_workspace
        init_learning_workspace(workspace_path)

    # Inject a fixed-cwd resolver so file tools write into the learning
    # workspace, not into the process cwd (relevant when running berry
    # from the source tree but pointing the LLM at a learning workspace
    # via BERRY_LEARNING_WORKSPACE).
    cwd_resolver = (lambda _sid: workspace_path) if workspace_path else None

    runtime, system_prompt = _build_runtime(
        approval_channel=approval_channel,
        cwd_resolver=cwd_resolver,
    )

    # Append the learning persona + bootstrap instruction to the system prompt
    # so the LLM (a) knows it's running in learning mode, (b) loads SKILL.md
    # via the `skill` tool on its first turn before doing anything else.
    # Shared with web entrypoint via core/skills/learning_persona.py.
    if workspace_path is not None:
        from berry.core.skills.learning_persona import augment_system_prompt

        system_prompt = augment_system_prompt(system_prompt, workspace_path)

    runner = _CliTurnRunner(runtime, system_prompt)

    adapter = FeishuRuntimeAdapter(
        runner=runner,
        state_dir=state_dir,
        default_user_id=user_id,
        workspace_path=workspace_path,
    )
    approval_channel.set_chat_resolver(adapter.chat_resolver)
    set_feishu_runtime(adapter)

    # 注册 todo 事件监听器 — todo_write 执行后飞书发进度卡片
    _register_todo_listener(adapter, lark_client, account.account.account_id)

    # 注册 SUGGEST 事件监听器 — LLM 调 ask_user_question 工具后,
    # EventBus 发 SuggestionEmitted,这个 listener 翻译成飞书卡片。
    # 通用机制(不再 learning 专用),所有走飞书的 skill 都享受。
    from berry.channels.feishu.event_listener import (
        install_feishu_event_listener,
    )
    install_feishu_event_listener(
        lark_client=lark_client,
        chat_resolver=adapter.chat_resolver,
    )
    if workspace_path is not None:
        logger.info(
            "feishu_learning_skill_enabled",
            workspace_path=str(workspace_path),
        )

    logger.info(
        "feishu_entrypoint_starting",
        app_id=account.account.app_id,
        bot_name=account.account.bot_name,
        state_dir=str(state_dir),
        dm_policy=feishu_settings.dm_policy,
        allowlist_size=len(feishu_settings.allowed_open_ids),
        bot_open_id_configured=bool(feishu_settings.bot_open_id),
        group_allow_size=len(feishu_settings.group_allow_from),
        user_id=str(user_id),
    )

    try:
        await monitor_feishu_provider(
            [account],
            state_dir=state_dir,
            dm_policy=feishu_settings.dm_policy,
            allowed_open_ids=list(feishu_settings.allowed_open_ids),
            group_allow_from=list(feishu_settings.group_allow_from),
        )
    finally:
        await engine.dispose()


def main() -> None:
    """同步入口。"""
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("feishu_entrypoint_interrupted")


def _register_todo_listener(
    adapter: FeishuRuntimeAdapter,
    lark_client: object,
    account_id: str,
) -> None:
    """注册 todo 事件监听器,收到更新时发飞书进度卡片。"""
    from berry.channels.feishu import send as send_mod
    from berry.core.agent.todo_event import TodoUpdatedEvent, register_todo_listener

    def _on_todo_updated(event: TodoUpdatedEvent) -> None:
        chat_id, _, trigger_message_id = adapter.chat_resolver(event.conversation_id)
        if not chat_id:
            return

        card_md = render_todo_card(event.todos, event.old_todos)
        send_mod.send_card_markdown(
            lark_client,
            chat_id=chat_id,
            markdown=card_md,
            reply_to_message_id=trigger_message_id,
        )

    register_todo_listener(_on_todo_updated)


if __name__ == "__main__":
    main()
