"""Memory consolidator — deduplicate and merge memories when they accumulate.

Four-layer gating (aligned with claw-code autoDream):
  1. Time gate:    ≥ 24h since last consolidation
  2. Throttle:     avoid frequent filesystem scans
  3. File count:   ≥ 10 memory files
  4. Lock gate:    no other process consolidating
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import structlog

from berry.core.tools.memory.store import MemoryStore

logger = structlog.get_logger(__name__)

CONSOLIDATE_THRESHOLD = 10
LOCK_MAX_AGE_SECONDS = 3600  # 1 hour - in-flight lock TTL
MIN_INTERVAL_SECONDS = 24 * 3600  # 24h - minimum gap between successful runs
STAMP_FILENAME = ".consolidate-stamp"  # records last successful completion ts
LOCK_FILENAME = ".consolidate-lock"    # records currently-running pid


async def consolidate_memories(
    store: MemoryStore,
    invoke_llm: "LlmConsolidator | None" = None,
) -> int:
    """Consolidate memories if gating conditions are met.

    Returns number of changes made (0 if skipped or no changes).
    Fire-and-forget: never raises.
    """
    if invoke_llm is None:
        return 0

    try:
        return await _do_consolidate(store, invoke_llm)
    except Exception:
        logger.warning("memory_consolidate_failed", exc_info=True)
        return 0


async def _do_consolidate(
    store: MemoryStore,
    invoke_llm: "LlmConsolidator",
) -> int:
    memory_dir = store.memory_dir
    if not memory_dir.is_dir():
        return 0

    # Gate 1: file count
    entries = store.list_all()
    if len(entries) < CONSOLIDATE_THRESHOLD:
        return 0

    # Gate 2: time since last successful consolidation (24h)
    # `.consolidate-stamp` mtime = last successful completion. Independent of
    # the in-flight lock so that "currently running" and "ran recently"
    # are decoupled — previously they shared one file and finally cleaned it up,
    # making the 24h gate a no-op (consolidator ran every turn).
    stamp_path = memory_dir / STAMP_FILENAME
    if stamp_path.is_file():
        try:
            stamp_age = time.time() - stamp_path.stat().st_mtime
            if stamp_age < MIN_INTERVAL_SECONDS:
                return 0
        except OSError:
            pass

    # Gate 3: in-flight lock (prevent concurrent runs in same/neighbor process)
    lock_path = memory_dir / LOCK_FILENAME
    if lock_path.is_file():
        try:
            lock_age = time.time() - lock_path.stat().st_mtime
            if lock_age < LOCK_MAX_AGE_SECONDS:
                return 0  # Another run in flight
            # Stale lock (process died), clean up and continue
            lock_path.unlink()
        except OSError:
            pass

    # Gate 4: acquire lock
    _acquire_lock(lock_path)

    try:
        # Build prompt with all memory contents
        contents: list[str] = []
        for entry in entries:
            contents.append(
                f"## {entry.name} (type: {entry.type})\n"
                f"Description: {entry.description}\n"
                f"{entry.body}\n"
            )

        prompt = (
            "Here are all memory files. Please:\n"
            "1. Merge duplicates\n"
            "2. Remove clearly outdated ones\n"
            "3. Fix contradictions\n"
            "4. Keep the format: name, type, description, body\n\n"
            "Return JSON array: [{name, type, description, body}]\n"
            "If no changes needed, return exactly: NO_CHANGES\n\n"
            + "\n".join(contents)
        )

        result = await invoke_llm(prompt)

        if result.strip().upper() == "NO_CHANGES":
            logger.info("memory_consolidate_no_changes")
            return 0

        new_memories = _parse_consolidated(result)
        if not new_memories:
            return 0

        # Replace all files
        for old in entries:
            store.delete(old.name)
        for mem in new_memories:
            store.write(
                mem.get("name", "unnamed"),
                mem.get("type", "user"),
                mem.get("description", ""),
                mem.get("body", ""),
            )

        logger.info("memory_consolidated", count=len(new_memories))
        return len(new_memories)

    finally:
        _release_lock(lock_path)


def _acquire_lock(lock_path: Path) -> None:
    """Create lock file with PID and timestamp."""
    try:
        lock_path.write_text(
            f"pid={os.getpid()}\nts={time.time()}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _release_lock(lock_path: Path) -> None:
    """Remove lock file."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


def _parse_consolidated(text: str) -> list[dict[str, str]]:
    """Parse JSON array from LLM consolidation response."""
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


type LlmConsolidator = callable  # (prompt: str) -> Awaitable[str]
