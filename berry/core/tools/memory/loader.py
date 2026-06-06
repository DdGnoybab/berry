"""Memory loader — select and inject relevant memories into the current turn.

Two paths:
  1. Index always in system prompt (handled by prompt.py)
  2. Full content injected on demand via side-query (this module)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import structlog

from berry.core.tools.memory.store import MemoryEntry, MemoryStore

logger = structlog.get_logger(__name__)

MAX_SELECTED_MEMORIES = 5
MAX_BODY_LINES = 200
MAX_BODY_BYTES = 4096


async def select_relevant_memories(
    recent_user_text: str,
    catalog: list[MemoryEntry],
    *,
    invoke_llm: "LlmInvoker | None" = None,
) -> list[str]:
    """Select relevant memory filenames via LLM side-query.

    Falls back to keyword matching if LLM is unavailable or fails.
    Returns list of memory filenames (e.g. ["user-prefer-tabs.md"]).
    """
    if not catalog:
        return []

    if invoke_llm is None:
        return _keyword_fallback(recent_user_text, catalog)

    try:
        return await _llm_select(recent_user_text, catalog, invoke_llm)
    except Exception:
        logger.warning("memory_side_query_failed", exc_info=True)
        return _keyword_fallback(recent_user_text, catalog)


async def _llm_select(
    recent_text: str,
    catalog: list[MemoryEntry],
    invoke_llm: "LlmInvoker",
) -> list[str]:
    """LLM-based memory selection (side-query)."""
    catalog_lines = [
        f"{i}: {e.name} — {e.description}" for i, e in enumerate(catalog)
    ]
    catalog_text = "\n".join(catalog_lines)

    prompt = (
        "Select relevant memory indices based on the recent user message. "
        "Return a JSON array of indices, e.g. [0, 2]. "
        "If nothing is relevant, return []. "
        "Be selective — only pick memories that directly apply.\n\n"
        f"Recent user message:\n{recent_text[:500]}\n\n"
        f"Memory catalog:\n{catalog_text}"
    )

    result = await invoke_llm(prompt)
    indices = _parse_indices(result)
    selected: list[str] = []
    for idx in indices:
        if 0 <= idx < len(catalog) and len(selected) < MAX_SELECTED_MEMORIES:
            selected.append(catalog[idx].filename)
    return selected


def _parse_indices(text: str) -> list[int]:
    """Extract JSON array of integers from LLM response."""
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group())
    except (json.JSONDecodeError, TypeError):
        return []


def _keyword_fallback(
    recent_text: str,
    catalog: list[MemoryEntry],
) -> list[str]:
    """Simple keyword matching fallback."""
    text_lower = recent_text.lower()
    selected: list[str] = []
    for entry in catalog:
        if len(selected) >= MAX_SELECTED_MEMORIES:
            break
        searchable = f"{entry.name} {entry.description}".lower()
        # Check if any word >= 4 chars from the entry appears in the text
        for word in searchable.split():
            word = word.strip(".,:;!?")
            if len(word) >= 4 and word in text_lower:
                selected.append(entry.filename)
                break
    return selected


def build_memory_injection(entries: list[MemoryEntry]) -> str:
    """Build a <system-reminder> block for injected memory content."""
    if not entries:
        return ""
    lines = ["<system-reminder>", "Relevant memories:", ""]
    for entry in entries:
        lines.append(f"- {entry.name}: {entry.description}")
        # Truncate body
        body_lines = entry.body.split("\n")[:MAX_BODY_LINES]
        body_text = "\n".join(body_lines)
        if len(body_text) > MAX_BODY_BYTES:
            body_text = body_text[:MAX_BODY_BYTES] + "..."
        lines.append(body_text)
        lines.append("")
    lines.append("</system-reminder>")
    return "\n".join(lines)


def load_relevant_memories(
    memory_dir: Path,
    filenames: list[str],
) -> list[MemoryEntry]:
    """Load full content of selected memory files."""
    store = MemoryStore(memory_dir)
    entries: list[MemoryEntry] = []
    for fname in filenames:
        slug = fname.replace(".md", "")
        entry = store.read(slug)
        if entry:
            entries.append(entry)
    return entries


# Type alias for the LLM invocation callback
type LlmInvoker = callable  # (prompt: str) -> Awaitable[str]
