"""Feishu session 持久化 — 复用 berry 现有 SessionStore(jsonl)。

对齐 openclaw `extensions/feishu/src/session-conversation.ts`(简化):
session 文件落在 `<state_dir>/feishu/sessions/<safe_conversation_id>/`,
schema 复用 `core.agent.session_store.SessionStore`(meta.json + messages.jsonl
+ rotation),不重复造轮子。

为什么不放进 berry 项目的 `data/projects/<user>/<proj>/sessions/`(CLI 用的
那套):MVP 飞书 channel 没有 project 概念,用户进 DM 直接对话,不存在
project_id。等后期把飞书也接进 project 体系再迁。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from berry.core.agent.persistence import load_agent_session
from berry.core.agent.session import AgentSession
from berry.core.agent.session_store import SessionStore
from berry.domain.enums import Channel, SessionStatus

_SAFE_CONVERSATION_ID_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _safe_conversation_id(conversation_id: str) -> str:
    """Conversation id → 文件夹名安全形式(`feishu:acct:direct:ou_x` →
    `feishu_acct_direct_ou_x`)。"""
    return _SAFE_CONVERSATION_ID_RE.sub("_", conversation_id)


def feishu_session_dir(state_dir: Path, conversation_id: str) -> Path:
    return state_dir / "feishu" / "sessions" / _safe_conversation_id(conversation_id)


def load_or_create_session(
    *,
    state_dir: Path,
    conversation_id: str,
    user_id: UUID,
) -> tuple[AgentSession, SessionStore]:
    """根据 conversation_id 加载会话历史 — 没有就建一个新的。

    Args:
        state_dir: 飞书 channel 自己的状态根目录(默认 ~/.berry,见
            entrypoints/feishu)。
        conversation_id: 形如 `feishu:<acct>:direct:<open_id>`。
        user_id: 会话归属(MVP 默认用 `ensure_default_user` 拿到的固定 UUID)。

    Returns:
        `(session, store)` — store 给上层用来 append_message,session 给
        ConversationRuntime.run_turn 用。
    """
    sid_dir = feishu_session_dir(state_dir, conversation_id)
    store = SessionStore(sid_dir)

    existing = load_agent_session(store)
    if existing is not None:
        return existing, store

    # 不存在,创建一个新的 session。session_id 直接用 conversation_id —
    # 飞书侧 conversation 一对一映射,不需要单独发 session_id。
    # project_id 用一个固定的 placeholder UUID(MVP 没 project 概念)。
    project_id_placeholder = uuid.uuid5(uuid.NAMESPACE_DNS, "berry-feishu-placeholder")
    meta = store.create(
        session_id=conversation_id,
        user_id=user_id,
        project_id=project_id_placeholder,
        channel=Channel.FEISHU.value,
    )
    session = AgentSession(
        id=meta.id,
        user_id=user_id,
        channel=Channel.FEISHU,
        chat_id=None,
        status=SessionStatus.ACTIVE,
        title=None,
        messages=[],
        created_at=datetime.fromisoformat(meta.started_at),
        updated_at=datetime.fromisoformat(meta.started_at),
    )
    return session, store


def now_utc() -> datetime:
    return datetime.now(UTC)
