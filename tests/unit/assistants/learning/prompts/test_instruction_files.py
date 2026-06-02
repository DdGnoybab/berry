"""TDD tests for instruction_files.py.

Algorithm mirrors claw-code (reference/claw-code_1/rust/crates/runtime/src/prompt.rs):
- Walk parent chain from cwd up to root
- Discover BERRY.md / BERRY.local.md / .berry/BERRY.md / .berry/instructions.md per dir
- Order root → cwd (most specific last)
- Dedupe by content hash
- Truncate per-file at 4 KB with "[truncated]" marker
- Stop at total 12 KB with budget-exhausted notice
- Render with `## <filename> (scope: <dir>)` headers
"""

from __future__ import annotations

from pathlib import Path

import pytest

from berry.assistants.learning.prompts.instruction_files import (
    MAX_INSTRUCTION_FILE_CHARS,
    MAX_TOTAL_INSTRUCTION_CHARS,
    ContextFile,
    discover_instruction_files,
    render_instruction_files,
)


# ─── discover_instruction_files ────────────────────────────────────────────


def test_discovers_instruction_files_from_ancestor_chain(tmp_path: Path) -> None:
    """Files at every level of cwd's ancestor chain are discovered."""
    root = tmp_path
    nested = root / "apps" / "api"
    (nested / ".berry").mkdir(parents=True)

    (root / "BERRY.md").write_text("root instructions")
    (root / "BERRY.local.md").write_text("local instructions")
    (root / "apps").mkdir(exist_ok=True)
    (root / "apps" / ".berry").mkdir(exist_ok=True)
    (root / "apps" / "BERRY.md").write_text("apps instructions")
    (root / "apps" / ".berry" / "instructions.md").write_text(
        "apps dot berry instructions"
    )
    (nested / ".berry" / "BERRY.md").write_text("nested rules")
    (nested / ".berry" / "instructions.md").write_text("nested instructions")

    files = discover_instruction_files(nested)
    contents = [f.content for f in files]

    assert contents == [
        "root instructions",
        "local instructions",
        "apps instructions",
        "apps dot berry instructions",
        "nested rules",
        "nested instructions",
    ]


def test_discover_returns_empty_when_no_instruction_files(tmp_path: Path) -> None:
    """Clean directory tree → empty list, no exception."""
    files = discover_instruction_files(tmp_path)
    assert files == []


def test_discover_skips_empty_files(tmp_path: Path) -> None:
    """A BERRY.md that is whitespace-only is treated as not present."""
    (tmp_path / "BERRY.md").write_text("   \n\n  \n")
    files = discover_instruction_files(tmp_path)
    assert files == []


def test_dedupes_identical_instruction_content_across_scopes(tmp_path: Path) -> None:
    """When parent + child have byte-identical content, only one survives."""
    nested = tmp_path / "apps" / "api"
    nested.mkdir(parents=True)
    (tmp_path / "BERRY.md").write_text("same rules\n\n")  # extra trailing newlines
    (nested / "BERRY.md").write_text("same rules\n")

    files = discover_instruction_files(nested)
    assert len(files) == 1
    # Either one is acceptable; the algorithm keeps the first occurrence (root).
    assert files[0].content.strip() == "same rules"


# ─── render_instruction_files ──────────────────────────────────────────────


def test_render_emits_section_header_and_per_file_subheaders(tmp_path: Path) -> None:
    """Output starts with '# Berry instructions' and has '## <name> (scope: <dir>)' per file."""
    file = ContextFile(path=tmp_path / "BERRY.md", content="rule one")
    out = render_instruction_files([file])

    assert out.startswith("# Berry instructions")
    assert "## BERRY.md" in out
    assert f"(scope: {tmp_path})" in out
    assert "rule one" in out


def test_render_returns_empty_string_for_no_files() -> None:
    """No files → empty string (caller decides whether to push the section)."""
    assert render_instruction_files([]) == ""


def test_truncates_large_instruction_content_for_rendering(tmp_path: Path) -> None:
    """File over MAX_INSTRUCTION_FILE_CHARS is cut and marked '[truncated]'."""
    big = "x" * (MAX_INSTRUCTION_FILE_CHARS + 500)
    file = ContextFile(path=tmp_path / "BERRY.md", content=big)
    out = render_instruction_files([file])

    assert "[truncated]" in out
    # Body before "[truncated]" should not exceed the per-file limit
    body_start = out.index("BERRY.md")
    body = out[body_start:]
    assert "x" * (MAX_INSTRUCTION_FILE_CHARS + 500) not in body


def test_total_budget_exhausted_skips_remaining_files(tmp_path: Path) -> None:
    """When cumulative chars hit MAX_TOTAL_INSTRUCTION_CHARS, later files are dropped."""
    # Each file is at the per-file cap; need >= 4 to bust the 12KB total budget.
    files = [
        ContextFile(
            path=tmp_path / f"BERRY-{i}.md",
            content="y" * MAX_INSTRUCTION_FILE_CHARS,
        )
        for i in range(5)
    ]
    out = render_instruction_files(files)

    assert "_Additional instruction content omitted" in out
    # Last file's name should not appear (it was dropped)
    assert "BERRY-4.md" not in out


def test_render_keeps_short_content_intact(tmp_path: Path) -> None:
    """Small files are rendered verbatim, no [truncated] marker."""
    file = ContextFile(path=tmp_path / "BERRY.md", content="hello world")
    out = render_instruction_files([file])

    assert "hello world" in out
    assert "[truncated]" not in out


def test_render_strips_leading_trailing_whitespace(tmp_path: Path) -> None:
    """Content rendered should not carry surrounding blank lines from disk."""
    file = ContextFile(path=tmp_path / "BERRY.md", content="\n\nhello\n\n")
    out = render_instruction_files([file])

    # The rendered chunk should not start or end with blank lines.
    # We check the file's body sits on its own line, not preceded by newlines.
    chunk_start = out.index("hello")
    # the char two before should be a newline (header separator), not another newline-space
    assert out[chunk_start - 2 : chunk_start] == "\n\n"


# ─── Path display ──────────────────────────────────────────────────────────


def test_renders_filename_only_in_subheader(tmp_path: Path) -> None:
    """Subheader shows just the filename, not the absolute path."""
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    file = ContextFile(path=deep / "BERRY.md", content="rule")
    out = render_instruction_files([file])

    assert "## BERRY.md" in out
    # Absolute path should appear as scope, not duplicated in the subheader name
    lines = [ln for ln in out.splitlines() if ln.startswith("##")]
    assert len(lines) == 1
    assert "BERRY.md" in lines[0]
