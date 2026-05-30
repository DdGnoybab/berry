"""In-memory business model for an agent conversation.

Mirrors db.models.Session 1:1 in identity fields, but additionally carries
the full message list. Loaded from / saved to DB via persistence.py.

MVP fields only; reserved fields (compaction / fork / workspace_root /
last_health_check_ms) deferred until Round 6+ — adding them now would be
YAGNI per CLAUDE.md §6 "现在不做" clause.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from berry.core.llm.types import LlmMessage
from berry.domain.enums import Channel, SessionStatus


class AgentSession(BaseModel):
    """Business-layer agent session: identity + ordered message history."""

    # Identity (loaded from sessions row)
    id: UUID
    user_id: UUID
    channel: Channel
    chat_id: str | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    title: str | None = None

    # Conversation history (loaded from messages rows, ordered by created_at)
    messages: list[LlmMessage] = Field(default_factory=list)

    # Timestamps (read from DB; business code does not mutate)
    created_at: datetime
    updated_at: datetime

    # ─── Helpers ───

    def push_user_text(self, text: str) -> LlmMessage:
        """Append a user text message and return it (caller persists it)."""
        msg = LlmMessage.user(text)
        self.messages.append(msg)
        return msg

    def push_message(self, message: LlmMessage) -> None:
        """Append a pre-built message (assistant reply, tool result, etc)."""
        self.messages.append(message)
