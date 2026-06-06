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
        from berry.assistants.learning.init_workspace import init_learning_workspace
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
    if workspace_path is not None:
        system_prompt = _augment_system_prompt_for_learning(system_prompt, workspace_path)

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

    # 注册 learning SUGGEST 监听器 — LLM 写新 SUGGEST 到 progress.json 后,
    # 飞书发出建议卡片让用户选下一步。仅在 workspace_path 解析成功时启用。
    if workspace_path is not None:
        _register_learning_suggest_listener(adapter, lark_client)
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


def _augment_system_prompt_for_learning(base_prompt: str, workspace_path: Path) -> str:
    """Append the learning persona + bootstrap instruction to the system prompt.

    Three things get added:
      1. The persona (``berry/assistants/learning/prompts/system.md``) — defines
         the assistant as berry-L, lays out the iron law, etc.
      2. LEARNER.md content from the workspace, if present — the user's profile.
      3. A hard bootstrap instruction telling the LLM to invoke the ``learning``
         skill via the ``skill`` tool on its first turn — this loads SKILL.md
         and makes the state machine rules active.

    Without (3), the LLM sees the persona but doesn't know it MUST follow the
    state machine — it'll improvise. So this is the linchpin that connects
    the prompt to the SKILL.md rules.
    """
    parts: list[str] = [base_prompt]

    # 1. persona
    persona_path = (
        Path(__file__).parent.parent / "assistants" / "learning" / "prompts" / "system.md"
    )
    if persona_path.is_file():
        try:
            parts.append("\n\n" + persona_path.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning(
                "learning_persona_read_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

    # 2. LEARNER.md (if present)
    learner_md = workspace_path / "LEARNER.md"
    if learner_md.is_file():
        try:
            content = learner_md.read_text(encoding="utf-8").strip()
            if content:
                parts.append(
                    "\n\n# Learner Profile (loaded from workspace LEARNER.md)\n\n"
                    + content
                )
        except OSError as exc:
            logger.warning(
                "learner_md_read_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

    # 3. bootstrap instruction (the linchpin)
    parts.append(
        "\n\n# Learning Mode (ACTIVE)\n\n"
        "This workspace is configured for the berry-L learning assistant.\n\n"
        "**On EVERY turn**, your FIRST tool call MUST be invoking the `skill` "
        "tool with `skill=\"learning\"` to load the state machine rules. "
        "Treat the loaded SKILL.md as a HARD CONTRACT — its instructions "
        "override any default behavior you would otherwise apply.\n\n"
        "Do NOT skip this step \"because you remember the rules\" — the file "
        "is the source of truth, conversation memory is not. Read it every turn."
    )
    return "".join(parts)


def _register_learning_suggest_listener(
    adapter: FeishuRuntimeAdapter,
    lark_client: object,
) -> None:
    """Register the learning skill's SUGGEST listener.

    When ``progress_watcher`` notices a new ``current.last_suggestion`` after
    a turn, render a SUGGEST card and send it as a reply under the user's
    triggering message.
    """
    from berry.assistants.learning.cards import build_suggest_card
    from berry.assistants.learning.progress_watcher import (
        SuggestEmittedEvent,
        get_default_watcher,
    )
    from berry.channels.feishu import send as send_mod

    def _on_suggest(event: SuggestEmittedEvent) -> None:
        chat_id, user_open_id, trigger_message_id = adapter.chat_resolver(
            event.conversation_id
        )
        if not chat_id:
            logger.debug(
                "feishu_suggest_skipped_no_chat",
                conversation_id=event.conversation_id,
            )
            return
        sg = event.suggestion
        atom_label = event.atom or "?"
        try:
            card_json = build_suggest_card(
                suggestion_id=sg.get("suggestion_id", "sg_unknown"),
                atom_label=atom_label,
                context=sg.get("context", "post_assess"),
                score=sg.get("score"),
                weak_points=sg.get("weak_points") or [],
                options=sg.get("options") or [],
                extra_note=sg.get("extra_note"),
                sub_menu=sg.get("sub_menu"),
                user_open_id=user_open_id,
                chat_id=chat_id,
            )
        except Exception as exc:  # noqa: BLE001 — bad suggestion shape shouldn't crash listener
            logger.warning(
                "feishu_suggest_card_build_failed",
                conversation_id=event.conversation_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return
        send_mod.send_approval_card(
            lark_client,
            chat_id=chat_id,
            card_json=card_json,
            reply_to_message_id=trigger_message_id,
        )

    get_default_watcher().register_listener(_on_suggest)


if __name__ == "__main__":
    main()
