"""TDD tests for project_context.py.

Round 2 scope:
- Scan <cwd>/<notes_dir>/ for .md files (no recursion into subdirs of notes_dir).
- For each file collect: relpath / last_modified (YYYY-MM-DD) / size_bytes / is_empty.
- Render as the # Learning project context section.
- Cap notes index at 50 files; cap whole section at 4 KB; emit truncation notice
  on the cap line.
- Notes index sorted by relative path so the order is stable across runs.
- Notes_dir absent or empty → still renders the section header + cwd + date,
  with `Notes discovered: 0`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from berry.assistants.learning.prompts.project_context import (
    MAX_NOTES_LISTED,
    MAX_PROJECT_CONTEXT_CHARS,
    NoteEntry,
    ProjectContext,
    discover_project_context,
    render_project_context,
)


# ─── discover_project_context ──────────────────────────────────────────────


def test_discover_returns_empty_notes_when_dir_absent(tmp_path: Path) -> None:
    """notes_dir doesn't exist → notes_index is empty, fields still populated."""
    ctx = discover_project_context(tmp_path, "2026-05-31", "notes")
    assert ctx.cwd == tmp_path
    assert ctx.current_date == "2026-05-31"
    assert ctx.notes_dir == "notes"
    assert ctx.notes_index == []


def test_discover_lists_md_files_in_notes_dir(tmp_path: Path) -> None:
    """Each top-level .md file in notes_dir produces a NoteEntry."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "01-redis-basics.md").write_text("hello")
    (notes / "02-data-types.md").write_text("hello there")

    ctx = discover_project_context(tmp_path, "2026-05-31", "notes")
    relpaths = [n.relpath for n in ctx.notes_index]

    assert relpaths == ["notes/01-redis-basics.md", "notes/02-data-types.md"]


def test_discover_ignores_non_md_files(tmp_path: Path) -> None:
    """Only .md is listed; .txt / .py / etc. are ignored."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("md")
    (notes / "b.txt").write_text("txt")
    (notes / "c.py").write_text("# code")

    ctx = discover_project_context(tmp_path, "2026-05-31", "notes")
    assert [n.relpath for n in ctx.notes_index] == ["notes/a.md"]


def test_discover_marks_empty_files(tmp_path: Path) -> None:
    """A 0-byte .md file has is_empty=True."""
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "empty.md").write_text("")
    (notes / "filled.md").write_text("content")

    ctx = discover_project_context(tmp_path, "2026-05-31", "notes")
    by_path = {n.relpath: n for n in ctx.notes_index}

    assert by_path["notes/empty.md"].is_empty is True
    assert by_path["notes/filled.md"].is_empty is False


def test_discover_records_last_modified_iso_date(tmp_path: Path) -> None:
    """last_modified uses YYYY-MM-DD derived from file mtime."""
    notes = tmp_path / "notes"
    notes.mkdir()
    file = notes / "x.md"
    file.write_text("hi")
    # Stamp mtime to a known instant
    target = datetime(2026, 3, 15, 12, 0, tzinfo=UTC).timestamp()
    os.utime(file, (target, target))

    ctx = discover_project_context(tmp_path, "2026-05-31", "notes")
    assert ctx.notes_index[0].last_modified == "2026-03-15"


def test_discover_does_not_recurse_into_subdirs(tmp_path: Path) -> None:
    """Files in <notes>/<subdir>/ are NOT listed in Round 2."""
    notes = tmp_path / "notes"
    (notes / "sub").mkdir(parents=True)
    (notes / "top.md").write_text("top")
    (notes / "sub" / "deep.md").write_text("deep")

    ctx = discover_project_context(tmp_path, "2026-05-31", "notes")
    assert [n.relpath for n in ctx.notes_index] == ["notes/top.md"]


def test_discover_sorts_index_by_relpath(tmp_path: Path) -> None:
    """Order is deterministic (sorted by relpath), independent of filesystem order."""
    notes = tmp_path / "notes"
    notes.mkdir()
    for name in ("z.md", "a.md", "m.md"):
        (notes / name).write_text("x")

    ctx = discover_project_context(tmp_path, "2026-05-31", "notes")
    assert [n.relpath for n in ctx.notes_index] == [
        "notes/a.md",
        "notes/m.md",
        "notes/z.md",
    ]


def test_discover_honors_custom_notes_dir(tmp_path: Path) -> None:
    """notes_dir other than 'notes' is respected."""
    custom = tmp_path / "study-notes"
    custom.mkdir()
    (custom / "x.md").write_text("hi")

    ctx = discover_project_context(tmp_path, "2026-05-31", "study-notes")
    assert ctx.notes_dir == "study-notes"
    assert ctx.notes_index[0].relpath == "study-notes/x.md"


# ─── render_project_context ────────────────────────────────────────────────


def test_render_emits_required_header_lines(tmp_path: Path) -> None:
    """Section starts with '# Learning project context' and lists date/cwd/count."""
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=[],
    )
    out = render_project_context(ctx)

    assert out.startswith("# Learning project context")
    assert "Today's date is 2026-05-31." in out
    assert f"Working directory: {tmp_path}" in out
    assert "Notes discovered: 0" in out


def test_render_with_no_notes_omits_index_subheader(tmp_path: Path) -> None:
    """When notes_index is empty, do not render a 'Notes index:' subheader."""
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=[],
    )
    out = render_project_context(ctx)
    assert "Notes index:" not in out


def test_render_lists_each_note_with_metadata(tmp_path: Path) -> None:
    """Each NoteEntry produces a line with relpath + (last_modified, size)."""
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=[
            NoteEntry(
                relpath="notes/a.md",
                last_modified="2026-05-29",
                size_bytes=3200,
                is_empty=False,
            ),
        ],
    )
    out = render_project_context(ctx)

    assert "Notes index:" in out
    assert "notes/a.md" in out
    assert "2026-05-29" in out
    # Size shown as KB-ish; exact format is implementation choice but should
    # contain either "3.2 KB" or "3200 B" — assert one of them appears.
    assert "3.2 KB" in out or "3200 B" in out or "3.1 KB" in out


def test_render_marks_empty_notes(tmp_path: Path) -> None:
    """Empty files are flagged so the LLM knows it's a placeholder."""
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=[
            NoteEntry(
                relpath="notes/empty.md",
                last_modified="2026-05-30",
                size_bytes=0,
                is_empty=True,
            ),
        ],
    )
    out = render_project_context(ctx)
    assert "empty" in out.lower()


def test_render_truncates_when_index_exceeds_max(tmp_path: Path) -> None:
    """More than MAX_NOTES_LISTED files → truncate + emit count of omitted."""
    notes = [
        NoteEntry(
            relpath=f"notes/{i:03d}.md",
            last_modified="2026-05-31",
            size_bytes=100,
            is_empty=False,
        )
        for i in range(MAX_NOTES_LISTED + 5)
    ]
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=notes,
    )
    out = render_project_context(ctx)

    # Last note shouldn't appear (truncated)
    assert f"notes/{MAX_NOTES_LISTED + 4:03d}.md" not in out
    assert "另有" in out or "more" in out.lower() or "未列出" in out


def test_render_stays_under_section_size_cap(tmp_path: Path) -> None:
    """Even with many notes, the rendered section is <= MAX_PROJECT_CONTEXT_CHARS."""
    notes = [
        NoteEntry(
            relpath=f"notes/very-long-filename-to-pad-byte-count-{i:03d}.md",
            last_modified="2026-05-31",
            size_bytes=100,
            is_empty=False,
        )
        for i in range(MAX_NOTES_LISTED)
    ]
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=notes,
    )
    out = render_project_context(ctx)
    assert len(out) <= MAX_PROJECT_CONTEXT_CHARS


# ─── Loop spec § 4.2: discover_project_context picks up PROGRESS.md ────────


def test_discover_reads_progress_md(tmp_path: Path) -> None:
    """When PROGRESS.md exists, ctx.progress is populated."""
    (tmp_path / "PROGRESS.md").write_text("""\
> 最终目标: 深入理解 Redis

### [in_progress] 1. 数据结构原理
- 完成判据: 能解释 5 个核心结构
- 小目标:
  - [in_progress] 1.1 SDS — 设计原理与权衡
""")
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    assert ctx.progress is not None
    assert ctx.progress.goal == "深入理解 Redis"
    assert ctx.progress.active_milestone is not None
    assert ctx.progress.active_milestone.title == "数据结构原理"


def test_discover_progress_none_when_missing(tmp_path: Path) -> None:
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    assert ctx.progress is None


def test_discover_progress_none_when_unparseable(tmp_path: Path) -> None:
    """Garbage in PROGRESS.md → ctx.progress is None, no crash."""
    (tmp_path / "PROGRESS.md").write_text("just some random text without structure")
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    assert ctx.progress is None


def test_discover_lists_quizzes(tmp_path: Path) -> None:
    quizzes = tmp_path / "quizzes"
    quizzes.mkdir()
    (quizzes / "m1.1-q1.md").write_text("# Q1")
    (quizzes / "m1.1-q2.md").write_text("# Q2")

    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    relpaths = [q.relpath for q in ctx.quizzes_index]
    assert relpaths == ["quizzes/m1.1-q1.md", "quizzes/m1.1-q2.md"]


def test_discover_lists_references(tmp_path: Path) -> None:
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "redis-design.md").write_text("# Reference")

    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    relpaths = [r.relpath for r in ctx.references_index]
    assert relpaths == ["references/redis-design.md"]


def test_discover_skips_quizzes_when_dir_missing(tmp_path: Path) -> None:
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    assert ctx.quizzes_index == []


def test_discover_skips_references_when_dir_missing(tmp_path: Path) -> None:
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    assert ctx.references_index == []


# ─── render_project_context: progress / quizzes / references blocks ────────


def _ctx_with_progress_md(tmp_path: Path, progress_content: str) -> ProjectContext:
    (tmp_path / "PROGRESS.md").write_text(progress_content)
    return discover_project_context(tmp_path, "2026-06-01", "notes")


def test_render_omits_progress_block_when_none(tmp_path: Path) -> None:
    ctx = ProjectContext(
        cwd=tmp_path, current_date="2026-06-01", notes_dir="notes",
    )
    out = render_project_context(ctx)
    assert "Progress (from PROGRESS.md)" not in out


def test_render_includes_progress_block_when_present(tmp_path: Path) -> None:
    ctx = _ctx_with_progress_md(tmp_path, """\
> 最终目标: 深入理解 Redis

### [in_progress] 1. 数据结构原理
- 完成判据: 能解释 5 个核心结构
- 小目标:
  - [done] 1.1 SDS [9.5]
  - [in_progress] 1.2 ziplist
""")
    out = render_project_context(ctx)
    assert "Progress (from PROGRESS.md)" in out
    assert "Goal: 深入理解 Redis" in out


def test_render_progress_shows_milestone_counts(tmp_path: Path) -> None:
    ctx = _ctx_with_progress_md(tmp_path, """\
> 最终目标: x

### [done] 1. a
- 完成判据: c
### [in_progress] 2. b
- 完成判据: c
### [pending] 3. c
- 完成判据: c
### [pending] 4. d
- 完成判据: c
""")
    out = render_project_context(ctx)
    assert "Total milestones: 4" in out
    assert "Done: 1" in out
    assert "In progress: 1" in out
    assert "Pending: 2" in out


def test_render_progress_shows_active_milestone(tmp_path: Path) -> None:
    ctx = _ctx_with_progress_md(tmp_path, """\
> 最终目标: x
### [done] 1. a
- 完成判据: c
### [in_progress] 2. 过期与内存
- 完成判据: c
""")
    out = render_project_context(ctx)
    assert "Active milestone: 2. 过期与内存" in out


def test_render_progress_shows_small_goals_under_active(tmp_path: Path) -> None:
    ctx = _ctx_with_progress_md(tmp_path, """\
> 最终目标: x
### [in_progress] 1. 数据结构原理
- 完成判据: c
- 小目标:
  - [done] 1.1 SDS [9.5]
  - [in_progress] 1.2 ziplist
  - [pending] 1.3 quicklist
""")
    out = render_project_context(ctx)
    assert "Small goals (3 total):" in out
    assert "[done] 1.1 SDS" in out
    assert "[in_progress] 1.2 ziplist" in out
    assert "[pending] 1.3 quicklist" in out


def test_render_progress_notes_when_milestone_has_no_small_goals(
    tmp_path: Path,
) -> None:
    """Active milestone with no small goals → tell LLM to propose them."""
    ctx = _ctx_with_progress_md(tmp_path, """\
> 最终目标: x
### [in_progress] 1. 数据结构原理
- 完成判据: c
""")
    out = render_project_context(ctx)
    assert "small goals not yet decomposed" in out.lower()


def test_render_progress_average_score(tmp_path: Path) -> None:
    ctx = _ctx_with_progress_md(tmp_path, """\
> 最终目标: x
### [in_progress] 1. a
- 完成判据: c
- 小目标:
  - [done] 1.1 a [9.0]
  - [done] 1.2 b [8.0]
  - [in_progress] 1.3 c
""")
    out = render_project_context(ctx)
    assert "Average score so far: 8.5" in out
    assert "across 2 done small goal" in out


def test_render_quizzes_block_when_present(tmp_path: Path) -> None:
    quizzes = tmp_path / "quizzes"
    quizzes.mkdir()
    (quizzes / "m1.1-q1.md").write_text("# Q1")

    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    out = render_project_context(ctx)
    assert "Quizzes:" in out
    assert "quizzes/m1.1-q1.md" in out


def test_render_quizzes_caps_at_5_with_more_indicator(tmp_path: Path) -> None:
    quizzes = tmp_path / "quizzes"
    quizzes.mkdir()
    for i in range(7):
        (quizzes / f"m1.{i}-q1.md").write_text("# Q")

    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    out = render_project_context(ctx)
    # Should display "Quizzes: 7 .md files in quizzes/" then list <= 5 + "more"
    assert "Quizzes: 7" in out
    assert "more" in out.lower()


def test_render_references_lists_all(tmp_path: Path) -> None:
    refs = tmp_path / "references"
    refs.mkdir()
    (refs / "redis-design.md").write_text("# Ref")
    (refs / "another.md").write_text("# Another")

    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    out = render_project_context(ctx)
    assert "References:" in out
    assert "references/another.md" in out
    assert "references/redis-design.md" in out


def test_render_omits_quizzes_block_when_empty(tmp_path: Path) -> None:
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    out = render_project_context(ctx)
    assert "Quizzes:" not in out


def test_render_omits_references_block_when_empty(tmp_path: Path) -> None:
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    out = render_project_context(ctx)
    assert "References:" not in out


# ─── SESSION_LOG.md (Loop iteration §6.4) ──────────────────────────────────


def test_discover_reads_session_log(tmp_path: Path) -> None:
    """discover_project_context picks up SESSION_LOG.md and parses entries."""
    (tmp_path / "SESSION_LOG.md").write_text("""\
# Session log

## 2026-06-01 14:40 (session aaa)
- Milestone 1.2 redis-cli
- Pending: review-and-retest

## 2026-06-01 21:15 (session bbb)
- Resumed
""")
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    assert len(ctx.session_log) == 2
    assert ctx.session_log[0].session_id == "aaa"
    assert ctx.session_log[1].session_id == "bbb"


def test_discover_session_log_empty_when_missing(tmp_path: Path) -> None:
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    assert ctx.session_log == []


def test_render_recent_activity_block_when_session_log_present(tmp_path: Path) -> None:
    (tmp_path / "SESSION_LOG.md").write_text("""\
## 2026-06-01 14:40 (session aaa)
- Milestone 1.2 redis-cli, Quiz 4/10
- Pending: review-and-retest
""")
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    out = render_project_context(ctx)

    assert "Recent activity (from SESSION_LOG.md" in out
    assert "session aaa" in out


def test_render_recent_activity_caps_at_5_with_more_indicator(tmp_path: Path) -> None:
    """Only the most recent 5 entries should appear in the prompt."""
    body = "\n".join(
        f"## 2026-06-{i:02d} 10:00 (session s{i})\n- did stuff {i}\n"
        for i in range(1, 9)  # 8 entries
    )
    (tmp_path / "SESSION_LOG.md").write_text(body)
    ctx = discover_project_context(tmp_path, "2026-06-09", "notes")
    out = render_project_context(ctx)

    # Older 3 should not appear by id
    assert "session s1" not in out
    assert "session s3" not in out
    # Newest 5 should
    assert "session s4" in out
    assert "session s8" in out
    # Indicator that older entries were elided (count and a hint to read raw file)
    assert "3 earlier" in out
    assert "SESSION_LOG.md" in out


def test_render_open_issues_block_when_pending_entries_exist(tmp_path: Path) -> None:
    """⚠️ Open issues subsection appears when any visible entry has Pending."""
    (tmp_path / "SESSION_LOG.md").write_text("""\
## 2026-06-01 14:40 (session aaa)
- Quiz score 4/10
- Pending: review-and-retest milestone 1.2

## 2026-06-01 21:15 (session bbb)
- All good, advanced to 1.3
""")
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    out = render_project_context(ctx)

    assert "Open issues" in out or "open issues" in out.lower()
    # Should reference the pending entry's session
    assert "aaa" in out


def test_render_no_open_issues_block_when_no_pending(tmp_path: Path) -> None:
    (tmp_path / "SESSION_LOG.md").write_text("""\
## 2026-06-01 14:40 (session aaa)
- Quiz 9/10, marked done
""")
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    out = render_project_context(ctx)

    assert "Open issues" not in out
    assert "open issues" not in out.lower()


def test_render_omits_session_log_block_when_empty(tmp_path: Path) -> None:
    ctx = discover_project_context(tmp_path, "2026-06-01", "notes")
    out = render_project_context(ctx)
    assert "Recent activity" not in out
