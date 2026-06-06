"""MemoryStore — file-based persistent memory for cross-session knowledge.

Each memory is a Markdown file with YAML frontmatter under ``{data_root}/memory/``.
An index file ``MEMORY.md`` provides a one-line-per-link catalog injected into
the system prompt so the LLM knows what memories exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_VALID_TYPES = frozenset({"user", "feedback", "project", "reference"})
_INDEX_HEADER = "# Memory Index\n"


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """A single memory entry — corresponds to one .md file."""

    name: str
    type: str
    description: str
    body: str
    filename: str = field(default="")

    def __post_init__(self) -> None:
        if self.type not in _VALID_TYPES:
            raise ValueError(
                f"Invalid memory type {self.type!r}; must be one of {sorted(_VALID_TYPES)}"
            )


class MemoryStore:
    """File-based memory storage.  Pure file IO — no DB, no RAG."""

    def __init__(self, memory_dir: Path) -> None:
        self._dir = memory_dir

    @property
    def memory_dir(self) -> Path:
        return self._dir

    # ── CRUD ────────────────────────────────────────────────────────────

    def write(
        self,
        name: str,
        mem_type: str,
        description: str,
        body: str,
    ) -> Path:
        """Write a memory file and rebuild the index.  Returns the file path."""
        self._dir.mkdir(parents=True, exist_ok=True)
        slug = _slugify(name)
        filepath = self._dir / f"{slug}.md"
        content = (
            f"---\n"
            f"name: {name}\n"
            f"description: {description}\n"
            f"type: {mem_type}\n"
            f"---\n"
            f"\n"
            f"{body}\n"
        )
        filepath.write_text(content, encoding="utf-8")
        logger.info("memory_written", name=name, type=mem_type, path=str(filepath))
        self.rebuild_index()
        return filepath

    def read(self, name: str) -> MemoryEntry | None:
        """Read a single memory by name (slug or frontmatter name)."""
        slug = _slugify(name)
        filepath = self._dir / f"{slug}.md"
        if filepath.is_file():
            return _parse_memory_file(filepath)

        # Fallback: scan all files for frontmatter name match
        if not self._dir.is_dir():
            return None
        for f in self._dir.iterdir():
            if f.suffix == ".md" and f.name != "MEMORY.md":
                entry = _parse_memory_file(f)
                if entry and entry.name.lower() == name.lower():
                    return entry
        return None

    def delete(self, name: str) -> bool:
        """Delete a memory file by name.  Returns True if deleted."""
        slug = _slugify(name)
        filepath = self._dir / f"{slug}.md"
        if filepath.is_file():
            filepath.unlink()
            logger.info("memory_deleted", name=name)
            self.rebuild_index()
            return True

        # Fallback: scan frontmatter name
        if not self._dir.is_dir():
            return False
        for f in self._dir.iterdir():
            if f.suffix == ".md" and f.name != "MEMORY.md":
                entry = _parse_memory_file(f)
                if entry and entry.name.lower() == name.lower():
                    f.unlink()
                    logger.info("memory_deleted", name=entry.name)
                    self.rebuild_index()
                    return True
        return False

    def list_all(self) -> list[MemoryEntry]:
        """List all memory entries, sorted by name."""
        if not self._dir.is_dir():
            return []
        entries: list[MemoryEntry] = []
        for f in sorted(self._dir.iterdir()):
            if f.suffix == ".md" and f.name != "MEMORY.md":
                entry = _parse_memory_file(f)
                if entry:
                    entries.append(entry)
        return entries

    # ── Index ───────────────────────────────────────────────────────────

    def rebuild_index(self) -> None:
        """Rebuild MEMORY.md from all existing .md files."""
        self._dir.mkdir(parents=True, exist_ok=True)
        entries = self.list_all()
        lines = [_INDEX_HEADER]
        for entry in entries:
            slug = _slugify(entry.name)
            lines.append(f"- [{entry.name}]({slug}.md) — {entry.description}")
        index_path = self._dir / "MEMORY.md"
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def read_index(self) -> str:
        """Return the raw content of MEMORY.md, or empty string if absent."""
        index_path = self._dir / "MEMORY.md"
        if index_path.is_file():
            return index_path.read_text(encoding="utf-8")
        return ""

    # ── Helpers ─────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        """Number of memory files (excluding MEMORY.md)."""
        if not self._dir.is_dir():
            return 0
        return sum(
            1
            for f in self._dir.iterdir()
            if f.suffix == ".md" and f.name != "MEMORY.md"
        )


# ── Module-level helpers ────────────────────────────────────────────────


def _slugify(name: str) -> str:
    """Convert a name to a filesystem-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed"


def _parse_memory_file(filepath: Path) -> MemoryEntry | None:
    """Parse a memory .md file with YAML frontmatter."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except OSError:
        return None

    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None

    frontmatter = match.group(1)
    meta: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip("\"'")

    body = content[match.end() :].strip()

    return MemoryEntry(
        name=meta.get("name", filepath.stem),
        type=meta.get("type", "user"),
        description=meta.get("description", ""),
        body=body,
        filename=filepath.name,
    )
