"""AgentSession <-> filesystem conversion.

Old version went through DB (MessageRepo / SessionRepo); Stage 1 switches to
SessionStore (jsonl files).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from berry.core.agent.session import AgentSession
from berry.core.agent.session_store import SessionStore
from berry.core.llm.types import LlmMessage
from berry.domain.enums import Channel, SessionStatus


def load_agent_session(
    store: SessionStore,
) -> AgentSession | None:
    """Reconstruct AgentSession from a SessionStore.

    - Read meta.json
    - Load all messages.jsonl (including rotated)
    - Assemble into AgentSession instance

    No meta.json -> return None.
    """
    meta = store.read_meta()
    if meta is None:
        return None

    raw_messages = store.load_all_messages()
    messages = [_envelope_to_llm_message(env) for env in raw_messages]

    # AgentSession.id is currently typed as UUID. The file session_id
    # (e.g. "20260604T152300-a3d2") is not a real UUID, so we derive a
    # stable UUID via uuid5. Stage 2 will widen AgentSession.id to str.
    return AgentSession(
        id=_session_id_to_uuid(meta.id),
        user_id=UUID(meta.user_id),
        channel=Channel(meta.channel),
        chat_id=None,
        status=SessionStatus(meta.status),
        title=meta.title,
        messages=messages,
        created_at=datetime.fromisoformat(meta.started_at),
        updated_at=datetime.fromisoformat(meta.ended_at or meta.started_at),
    )


def save_message(
    store: SessionStore,
    message: LlmMessage,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append one LlmMessage to messages.jsonl."""
    store.append_message(message, metadata=metadata)


# ─── helpers ────────────────────────────────────────────


def _envelope_to_llm_message(env: dict[str, Any]) -> LlmMessage:
    """messages.jsonl one line -> LlmMessage (validated by pydantic).

    Unknown content block types raise ValidationError.
    """
    return LlmMessage.model_validate(
        {"role": env["role"], "content": env["content"]}
    )


def _session_id_to_uuid(s: str) -> UUID:
    """File session_id string -> derived stable UUID.

    Used because AgentSession.id is typed as UUID. Stage 2 will widen
    that type and remove this stub.
    """
    from uuid import NAMESPACE_OID, uuid5
    return uuid5(NAMESPACE_OID, s)
