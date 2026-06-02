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

    return AgentSession(
        id=meta.id,  # already a string
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
