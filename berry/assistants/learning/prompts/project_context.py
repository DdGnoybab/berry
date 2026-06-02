"""Build & render the # Learning project context section.

Sources surfaced to the LLM:
- ``<cwd>/<notes_dir>/*.md``           → notes index (file list + metadata)
- ``<cwd>/PROGRESS.md``                → parsed three-tier progress snapshot
- ``<cwd>/quizzes/*.md``               → quiz history (latest 5 listed)
- ``<cwd>/references/*.md``            → user-uploaded reference materials

Sort everything by relpath so the prompt is deterministic across runs.
The whole rendered section is capped at ``MAX_PROJECT_CONTEXT_CHARS`` (4 KB);
notes-index tail is dropped first if we exceed.

Loop spec § 4:
  docs/superpowers/specs/2026-06-01-learning-loop-implementation-design.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from berry.assistants.learning.prompts.instruction_files import ContextFile
from berry.assistants.learning.prompts.progress_parser import (
    ProgressSnapshot,
    parse_progress_md,
)
from berry.assistants.learning.prompts.session_log_parser import (
    SessionLogEntry,
    parse_session_log_md,
)

# Hard caps. Adjust only with an ADR.
MAX_NOTES_LISTED = 50
MAX_PROJECT_CONTEXT_CHARS = 4_000
MAX_QUIZZES_LISTED = 5  # Loop spec § 4.3 — show only the most recent N quizzes
MAX_SESSION_LOG_LISTED = 5  # Recent activity tail (most recent N entries)


@dataclass(frozen=True)
class NoteEntry:
    """One .md file's metadata for the prompt."""

    relpath: str            # path relative to cwd, e.g. "notes/01-intro.md"
    last_modified: str | None  # YYYY-MM-DD or None when mtime unavailable
    size_bytes: int
    is_empty: bool


@dataclass(frozen=True)
class ProjectContext:
    """Snapshot of the learning project's environment for one session.

    Captured once when the session starts; not refreshed mid-session
    (see system-prompt-design spec § 7).
    """

    cwd: Path
    current_date: str        # YYYY-MM-DD
    notes_dir: str           # relative dir name, e.g. "notes"
    notes_index: list[NoteEntry] = field(default_factory=list)
    instruction_files: list[ContextFile] = field(default_factory=list)

    # ── Loop spec § 4 additions ──
    progress: ProgressSnapshot | None = None
    quizzes_index: list[NoteEntry] = field(default_factory=list)
    references_index: list[NoteEntry] = field(default_factory=list)
    # ── Loop iteration §6.4: session continuity ──
    session_log: list[SessionLogEntry] = field(default_factory=list)


def discover_project_context(
    cwd: Path,
    current_date: str,
    notes_dir: str,
) -> ProjectContext:
    """Snapshot what the LLM should know about this learning workspace."""
    cwd = cwd.resolve()

    return ProjectContext(
        cwd=cwd,
        current_date=current_date,
        notes_dir=notes_dir,
        notes_index=_scan_md(cwd / notes_dir, notes_dir),
        progress=_read_progress(cwd),
        quizzes_index=_scan_md(cwd / "quizzes", "quizzes"),
        references_index=_scan_md(cwd / "references", "references"),
        session_log=_read_session_log(cwd),
    )


def _scan_md(directory: Path, relpath_prefix: str) -> list[NoteEntry]:
    """List top-level .md files in ``directory``, sorted by relpath.

    Returns [] if the directory does not exist. No recursion (Round 2 design,
    upheld through Round 2.5).
    """
    if not directory.is_dir():
        return []
    notes = [
        _describe_note(entry, relpath_prefix)
        for entry in directory.iterdir()
        if entry.is_file() and entry.suffix == ".md"
    ]
    notes.sort(key=lambda n: n.relpath)
    return notes


def _read_progress(cwd: Path) -> ProgressSnapshot | None:
    """Read and parse PROGRESS.md. Returns None if file missing or unparseable."""
    progress_path = cwd / "PROGRESS.md"
    if not progress_path.is_file():
        return None
    try:
        content = progress_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_progress_md(content)


def _read_session_log(cwd: Path) -> list[SessionLogEntry]:
    """Read and parse SESSION_LOG.md. Returns [] if file missing or unparseable."""
    log_path = cwd / "SESSION_LOG.md"
    if not log_path.is_file():
        return []
    try:
        content = log_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_session_log_md(content)


def render_project_context(ctx: ProjectContext) -> str:
    """Render the # Learning project context section.

    Layout (Loop spec § 4.3 + iteration §6.4):
      - head bullets (always)
      - Notes index               (when notes_index non-empty)
      - Progress block            (when progress non-None)
      - Recent activity block     (when session_log non-empty, capped at 5)
      - Open issues block         (when any visible session_log entry has Pending)
      - Quizzes block             (when quizzes_index non-empty, capped at 5)
      - References block          (when references_index non-empty, all listed)

    Total cap is ``MAX_PROJECT_CONTEXT_CHARS``. Notes index is the cuttable
    section if we exceed; everything else renders unchanged.
    """
    head = _render_head(ctx)
    progress_block = _render_progress(ctx.progress)
    recent_log = ctx.session_log[-MAX_SESSION_LOG_LISTED:]
    elided_log = len(ctx.session_log) - len(recent_log)
    recent_activity_block = _render_recent_activity(recent_log, elided_log, len(ctx.session_log))
    open_issues_block = _render_open_issues(recent_log)
    quizzes_block = _render_quizzes(ctx.quizzes_index)
    references_block = _render_references(ctx.references_index)

    fixed_tail_blocks = [
        b for b in (
            progress_block,
            recent_activity_block,
            open_issues_block,
            quizzes_block,
            references_block,
        ) if b
    ]
    fixed_tail = "\n\n" + "\n\n".join(fixed_tail_blocks) if fixed_tail_blocks else ""

    # Notes index has to fit in the remainder.
    if not ctx.notes_index:
        return head + fixed_tail

    listed = ctx.notes_index[:MAX_NOTES_LISTED]
    omitted = len(ctx.notes_index) - len(listed)

    while True:
        notes_block = _render_notes_block(listed, omitted)
        rendered = head + "\n" + notes_block + fixed_tail
        if len(rendered) <= MAX_PROJECT_CONTEXT_CHARS or len(listed) <= 1:
            return rendered
        listed = listed[:-1]
        omitted += 1


# ─── render helpers (per block) ────────────────────────────────────────────


def _render_head(ctx: ProjectContext) -> str:
    bullets = [
        f" - Today's date is {ctx.current_date}.",
        f" - Working directory: {ctx.cwd}",
        f" - Notes discovered: {len(ctx.notes_index)} .md files in {ctx.notes_dir}/.",
    ]
    return "\n".join(["# Learning project context", *bullets])


def _render_notes_block(listed: list[NoteEntry], omitted: int) -> str:
    lines = ["", "Notes index:"]
    for note in listed:
        lines.append(f"  {_format_note_line(note)}")
    if omitted > 0:
        lines.append(f"  ... (另有 {omitted} 个 .md 文件未列出)")
    return "\n".join(lines)


def _render_progress(progress: ProgressSnapshot | None) -> str:
    if progress is None:
        return ""

    counts = {"done": 0, "in_progress": 0, "pending": 0, "skipped": 0}
    for m in progress.milestones:
        counts[m.status] += 1
    counts_str = (
        f"Done: {counts['done']}, "
        f"In progress: {counts['in_progress']}, "
        f"Pending: {counts['pending']}"
    )
    if counts["skipped"]:
        counts_str += f", Skipped: {counts['skipped']}"

    lines = [
        "Progress (from PROGRESS.md):",
        f"  Goal: {progress.goal}",
        f"  Total milestones: {len(progress.milestones)} ({counts_str})",
    ]

    active = progress.active_milestone
    if active is not None:
        lines.append("")
        lines.append(f"  Active milestone: {active.index}. {active.title}")
        if active.small_goals:
            lines.append(f"    Small goals ({len(active.small_goals)} total):")
            for sg in active.small_goals:
                score_part = f" [{sg.score}]" if sg.score is not None else ""
                lines.append(f"      [{sg.status}] {sg.index} {sg.title}{score_part}")
        else:
            lines.append(
                "    (small goals not yet decomposed — Berry should propose 1-4 next)"
            )

    avg = progress.average_score
    if avg is not None:
        done_count = sum(
            1
            for m in progress.milestones
            for sg in m.small_goals
            if sg.status == "done" and sg.score is not None
        )
        suffix = "" if done_count == 1 else "s"
        lines.append("")
        lines.append(
            f"  Average score so far: {avg:.1f} (across {done_count} done small goal{suffix})"
        )

    return "\n".join(lines)


def _render_recent_activity(
    recent: list[SessionLogEntry], elided: int, total: int,
) -> str:
    """Render the most recent N session log entries.

    Each entry shows the timestamp + session id + a one-line digest of the
    body (first non-blank bullet). The full body is intentionally NOT
    rendered — the LLM can read SESSION_LOG.md raw if it wants details.
    """
    if not recent:
        return ""

    lines = [f"Recent activity (from SESSION_LOG.md, last {len(recent)} of {total}):"]
    for entry in recent:
        first_line = next(
            (ln.strip().lstrip("- ").strip() for ln in entry.body.splitlines() if ln.strip()),
            "(no content)",
        )
        lines.append(f"  {entry.timestamp} (session {entry.session_id}): {first_line}")
    if elided > 0:
        lines.append(f"  ... and {elided} earlier entries (read SESSION_LOG.md for full history)")
    return "\n".join(lines)


def _render_open_issues(recent: list[SessionLogEntry]) -> str:
    """Surface any Pending/Issue markers in the visible session log entries."""
    pending_entries = [e for e in recent if e.has_pending]
    if not pending_entries:
        return ""

    lines = ["⚠️ Open issues from previous sessions:"]
    for entry in pending_entries:
        # Pull the actual Pending/Issue line(s) for context
        pending_lines = [
            ln.strip()
            for ln in entry.body.splitlines()
            if ln.strip().startswith(("- Pending:", "- Issue:"))
        ]
        for pl in pending_lines:
            lines.append(f"  (session {entry.session_id}) {pl.lstrip('- ').strip()}")
    return "\n".join(lines)


def _render_quizzes(quizzes: list[NoteEntry]) -> str:
    if not quizzes:
        return ""

    lines = [f"Quizzes: {len(quizzes)} .md files in quizzes/"]
    listed = quizzes[:MAX_QUIZZES_LISTED]
    for q in listed:
        last = q.last_modified if q.last_modified else "—"
        lines.append(f"  {q.relpath} (last modified: {last})")
    overflow = len(quizzes) - len(listed)
    if overflow > 0:
        lines.append(f"  ... and {overflow} more")
    return "\n".join(lines)


def _render_references(refs: list[NoteEntry]) -> str:
    if not refs:
        return ""
    lines = [f"References: {len(refs)} .md files in references/"]
    for r in refs:
        lines.append(f"  {r.relpath}")
    return "\n".join(lines)


# ─── internals ─────────────────────────────────────────────────────────────


def _describe_note(path: Path, notes_dir: str) -> NoteEntry:
    """Build a NoteEntry from a single .md path."""
    try:
        stat = path.stat()
        size_bytes = stat.st_size
        last_modified = (
            datetime.fromtimestamp(stat.st_mtime, tz=UTC).date().isoformat()
        )
    except OSError:
        size_bytes = 0
        last_modified = None

    is_empty = size_bytes == 0
    relpath = f"{notes_dir}/{path.name}"
    return NoteEntry(
        relpath=relpath,
        last_modified=last_modified,
        size_bytes=size_bytes,
        is_empty=is_empty,
    )


def _format_note_line(note: NoteEntry) -> str:
    """Format one note's line in the index."""
    size = _format_size(note.size_bytes)
    if note.is_empty:
        size = f"{size} — empty"
    last = note.last_modified if note.last_modified else "—"
    return f"{note.relpath}           (last modified: {last}, {size})"


def _format_size(size_bytes: int) -> str:
    """Human-friendly size: 0 B, 512 B, 3.2 KB."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    return f"{size_bytes / 1024:.1f} KB"
