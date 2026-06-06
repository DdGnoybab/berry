"""Memory extractor — auto-extract memories from conversation at end of turn.

Runs as a stop hook after the LLM finishes a turn (stop_reason == "end_turn").
Uses a lightweight LLM call to identify user preferences, constraints, or
project facts worth remembering.
"""

from __future__ import annotations

import json
import re

import structlog

from berry.core.llm.types import LlmMessage
from berry.core.tools.memory.store import MemoryStore

logger = structlog.get_logger(__name__)

MAX_RECENT_MESSAGES = 10
MAX_EXTRACTED_PER_TURN = 3


async def extract_memories(
    messages: list[LlmMessage],
    store: MemoryStore,
    invoke_llm: "LlmExtractor | None" = None,
) -> int:
    """Extract new memories from recent conversation.

    Returns the number of new memories written.
    Fire-and-forget: never raises.
    """
    if invoke_llm is None:
        return 0

    try:
        return await _do_extract(messages, store, invoke_llm)
    except Exception:
        logger.warning("memory_extract_failed", exc_info=True)
        return 0


async def _do_extract(
    messages: list[LlmMessage],
    store: MemoryStore,
    invoke_llm: "LlmExtractor",
) -> int:
    recent = messages[-MAX_RECENT_MESSAGES:]
    if not recent:
        return 0

    # Build dialogue text
    dialogue_lines: list[str] = []
    for msg in recent:
        role = msg.role
        text = _extract_text(msg)
        if text:
            dialogue_lines.append(f"{role}: {text[:500]}")
    dialogue = "\n".join(dialogue_lines)

    if not dialogue.strip():
        return 0

    # Existing memories (to avoid duplicates)
    existing = store.list_all()
    existing_text = "\n".join(
        f"- {e.name}: {e.description}" for e in existing
    ) or "(none)"

    prompt = (
        "From the dialogue below, extract user preferences, constraints, "
        "or project facts that are worth remembering for future sessions.\n\n"
        "Return a JSON array: [{name, type, description, body}].\n"
        "- name: short slug (e.g. 'user-prefer-tabs')\n"
        "- type: 'user' | 'feedback' | 'project' | 'reference'\n"
        "- description: one-line summary\n"
        "- body: full details\n\n"
        "If nothing new or already covered by existing memories, return [].\n"
        f"Be conservative — only extract stable, reusable knowledge.\n"
        f"Maximum {MAX_EXTRACTED_PER_TURN} items.\n\n"
        f"Existing memories:\n{existing_text}\n\n"
        f"Dialogue:\n{dialogue[:4000]}"
    )

    result = await invoke_llm(prompt)
    new_memories = _parse_memories(result)

    written = 0
    for mem in new_memories[:MAX_EXTRACTED_PER_TURN]:
        name = mem.get("name", "").strip()
        mem_type = mem.get("type", "").strip()
        description = mem.get("description", "").strip()
        body = mem.get("body", "").strip()

        if not name or not body:
            continue

        # Double-check: don't write if name already exists
        if store.read(name):
            continue

        store.write(name, mem_type or "user", description, body)
        written += 1

    if written:
        logger.info("memory_extracted", count=written)

    return written


def _extract_text(msg: LlmMessage) -> str:
    """Extract plain text from a message's content."""
    if isinstance(msg.content, str):
        return msg.content
    if isinstance(msg.content, list):
        parts: list[str] = []
        for block in msg.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return " ".join(parts)
    return ""


def _parse_memories(text: str) -> list[dict[str, str]]:
    """Parse JSON array of memory objects from LLM response."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group())
        if isinstance(parsed, list):
            return [m for m in parsed if isinstance(m, dict)]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


type LlmExtractor = callable  # (prompt: str) -> Awaitable[str]
