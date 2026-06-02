"""Discover, dedupe, truncate, and render BERRY.md instruction files.

Algorithm mirrors claw-code (reference/claw-code_1/rust/crates/runtime/src/prompt.rs:230-453):

  1. Walk parent chain from cwd up to root, collecting these per directory:
       BERRY.md, BERRY.local.md, .berry/BERRY.md, .berry/instructions.md
  2. Order root → cwd, so the most specific (deepest) file appears last and
     therefore wins when the LLM resolves overlapping rules.
  3. Skip empty / whitespace-only files.
  4. Dedupe by normalized content hash so a parent directory writing the same
     rule as a child does not get rendered twice.
  5. Per-file truncate at MAX_INSTRUCTION_FILE_CHARS (4 KB) with a "[truncated]"
     marker.
  6. Stop appending files once cumulative chars cross MAX_TOTAL_INSTRUCTION_CHARS
     (12 KB), and emit a budget-exhausted notice.
  7. Render each file under "## <filename> (scope: <dir>)" — the LLM sees both
     a stable subheader and the directory it applies to.

The numeric constants and the algorithm shape are byte-for-byte equivalent to
claw-code; we only changed the file-name set (CLAUDE.md → BERRY.md).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

# Single-file cap. claw-code: prompt.rs:43.
MAX_INSTRUCTION_FILE_CHARS = 4_000

# Cumulative cap across all instruction files. claw-code: prompt.rs:44.
MAX_TOTAL_INSTRUCTION_CHARS = 12_000

# Filenames searched in each ancestor directory, in fixed order.
_INSTRUCTION_FILE_NAMES: tuple[tuple[str, ...], ...] = (
    ("BERRY.md",),
    ("BERRY.local.md",),
    (".berry", "BERRY.md"),
    (".berry", "instructions.md"),
)

_TRUNCATED_MARKER = "\n\n[truncated]"
_BUDGET_EXHAUSTED_NOTICE = (
    "_Additional instruction content omitted after reaching the prompt budget._"
)


@dataclass(frozen=True)
class ContextFile:
    """A discovered instruction file ready for rendering."""

    path: Path
    content: str


def discover_instruction_files(cwd: Path) -> list[ContextFile]:
    """Walk cwd's ancestor chain and return discovered instruction files.

    Order is root → cwd (most specific last). Empty / whitespace-only files are
    skipped. Duplicate-content files (by normalized hash) collapse to the first
    occurrence so identical parent / child rules do not double-up.
    """
    cwd = cwd.resolve()
    directories: list[Path] = []
    cursor: Path | None = cwd
    while cursor is not None:
        directories.append(cursor)
        parent = cursor.parent
        cursor = parent if parent != cursor else None
    directories.reverse()  # root first, cwd last

    found: list[ContextFile] = []
    for directory in directories:
        for name_parts in _INSTRUCTION_FILE_NAMES:
            candidate = directory.joinpath(*name_parts)
            file = _read_if_nonempty(candidate)
            if file is not None:
                found.append(file)

    return _dedupe_by_content(found)


def render_instruction_files(files: list[ContextFile]) -> str:
    """Render the '# Berry instructions' section.

    Returns an empty string when no files are given (caller decides whether to
    push the section into the prompt at all).
    """
    if not files:
        return ""

    chunks: list[str] = ["# Berry instructions"]
    remaining = MAX_TOTAL_INSTRUCTION_CHARS

    for file in files:
        if remaining <= 0:
            chunks.append(_BUDGET_EXHAUSTED_NOTICE)
            break

        rendered_body = _truncate_for_render(file.content, remaining)
        # Count rendered_body length against the budget (not the original).
        consumed = min(len(rendered_body), remaining)
        remaining -= consumed

        chunks.append(f"## {file.path.name} (scope: {file.path.parent})")
        chunks.append(rendered_body)

    return "\n\n".join(chunks)


# ─── internals ─────────────────────────────────────────────────────────────


def _read_if_nonempty(path: Path) -> ContextFile | None:
    """Return ContextFile if file exists with non-whitespace content; else None."""
    try:
        content = path.read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return None
    if not content.strip():
        return None
    return ContextFile(path=path, content=content)


def _dedupe_by_content(files: list[ContextFile]) -> list[ContextFile]:
    """Drop later files whose normalized content matches an earlier one's."""
    seen: set[str] = set()
    out: list[ContextFile] = []
    for file in files:
        digest = _content_hash(_normalize_content(file.content))
        if digest in seen:
            continue
        seen.add(digest)
        out.append(file)
    return out


def _normalize_content(content: str) -> str:
    """Strip surrounding whitespace and collapse runs of blank lines.

    Matches claw-code's normalize_instruction_content + collapse_blank_lines so
    files differing only in whitespace dedupe correctly.
    """
    lines: list[str] = []
    previous_blank = False
    for line in content.splitlines():
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        lines.append(line.rstrip())
        previous_blank = is_blank
    return "\n".join(lines).strip()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _truncate_for_render(content: str, remaining_budget: int) -> str:
    """Trim content to fit the per-file cap (4 KB) and the remaining total budget."""
    trimmed = content.strip()
    hard_limit = min(MAX_INSTRUCTION_FILE_CHARS, remaining_budget)
    if len(trimmed) <= hard_limit:
        return trimmed
    return trimmed[:hard_limit] + _TRUNCATED_MARKER
