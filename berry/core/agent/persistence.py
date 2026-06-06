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
from berry.core.llm.types import (
    LlmMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from berry.domain.enums import Channel, SessionStatus
from berry.observability.logging import get_logger

logger = get_logger(__name__)


def load_agent_session(
    store: SessionStore,
) -> AgentSession | None:
    """Reconstruct AgentSession from a SessionStore.

    - Read meta.json
    - Load all messages.jsonl (including rotated)
    - Sanitize:strip orphan tool_use / tool_result blocks so providers don't
      400 on pairing violations across resumed turns
    - Assemble into AgentSession instance

    No meta.json -> return None.
    """
    meta = store.read_meta()
    if meta is None:
        return None

    raw_messages = store.load_all_messages()
    messages = [_envelope_to_llm_message(env) for env in raw_messages]
    messages = _sanitize_tool_pairing(messages)

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


def _sanitize_tool_pairing(messages: list[LlmMessage]) -> list[LlmMessage]:
    """Strip orphan tool_use / tool_result blocks from a loaded session.

    Anthropic (and most other providers) reject requests where:
      - a ``tool_result`` block has no preceding ``tool_use`` with the matching id
      - a ``tool_use`` is dangling at the end (no corresponding tool_result)

    Both happen in practice when a turn is interrupted (process crash, max
    iterations exceeded, mid-turn provider error). The session jsonl ends up
    with an unbalanced trailing pair, and EVERY future turn fails to load.

    This pass:
      1. Forward-pass: collect all tool_use ids in assistant messages.
      2. Drop tool_result blocks whose tool_use_id wasn't seen earlier
         (orphan tool_results — the case in user's session).
      3. Drop tool_use blocks whose id has no later tool_result
         (dangling tool_uses — usually the last assistant turn before crash).
      4. If a message becomes empty after stripping, drop the message.

    Logs ``persistence_sanitize_dropped`` when anything was dropped so users
    can tell sessions were repaired.
    """
    seen_tool_use_ids: set[str] = set()
    used_tool_use_ids: set[str] = set()
    for msg in messages:
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                seen_tool_use_ids.add(block.id)
            elif isinstance(block, ToolResultBlock):
                used_tool_use_ids.add(block.tool_use_id)

    orphan_results = used_tool_use_ids - seen_tool_use_ids
    dangling_uses = seen_tool_use_ids - used_tool_use_ids

    if not orphan_results and not dangling_uses:
        return messages

    logger.info(
        "persistence_sanitize_dropped",
        orphan_tool_results=len(orphan_results),
        dangling_tool_uses=len(dangling_uses),
        total_messages=len(messages),
    )

    cleaned: list[LlmMessage] = []
    for msg in messages:
        new_blocks: list[TextBlock | ToolUseBlock | ToolResultBlock] = []
        for block in msg.content:
            if isinstance(block, ToolUseBlock) and block.id in dangling_uses:
                continue
            if isinstance(block, ToolResultBlock) and block.tool_use_id in orphan_results:
                continue
            new_blocks.append(block)
        if not new_blocks:
            continue  # skip messages whose content fully evaporated
        cleaned.append(
            LlmMessage(
                role=msg.role,
                content=new_blocks,
            )
        )
    return cleaned
