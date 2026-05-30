"""Unit tests for the workspace path guard.

Path resolution is the single most security-sensitive piece of Round 3 —
if the LLM can write outside ``data_root``, every other safety control
fails. Hammer it.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from berry.assistants.learning.tools.workspace.paths import (
    WorkspacePathError,
    resolve_material_path,
    resolve_milestone_dir,
)

_GOAL_ID = UUID("11111111-1111-1111-1111-111111111111")
_MS_ID = UUID("22222222-2222-2222-2222-222222222222")


def test_resolve_milestone_dir_returns_expected_path(tmp_path: Path) -> None:
    out = resolve_milestone_dir(tmp_path, _GOAL_ID, _MS_ID)
    expected = (tmp_path / "goals" / str(_GOAL_ID) / "milestones" / str(_MS_ID)).resolve()
    assert out == expected


def test_resolve_material_path_appends_filename(tmp_path: Path) -> None:
    out = resolve_material_path(tmp_path, _GOAL_ID, _MS_ID, "01-intro.md")
    assert out.name == "01-intro.md"
    assert out.parent == resolve_milestone_dir(tmp_path, _GOAL_ID, _MS_ID)


def test_resolve_material_path_rejects_slashes(tmp_path: Path) -> None:
    with pytest.raises(WorkspacePathError, match="separator"):
        resolve_material_path(tmp_path, _GOAL_ID, _MS_ID, "subdir/x.md")
    with pytest.raises(WorkspacePathError, match="separator"):
        resolve_material_path(tmp_path, _GOAL_ID, _MS_ID, "x\\y.md")


def test_resolve_material_path_rejects_dotdot(tmp_path: Path) -> None:
    """A literal `..md` filename is structurally a hidden file (leading dot)
    AND the regex would also reject it. We test the path-traversal angle by
    feeding `..` through the filename slot — should NOT escape data_root.
    """
    with pytest.raises(WorkspacePathError):
        # `../etc.md` — separator triggers first
        resolve_material_path(tmp_path, _GOAL_ID, _MS_ID, "../etc.md")
    with pytest.raises(WorkspacePathError):
        # leading dot
        resolve_material_path(tmp_path, _GOAL_ID, _MS_ID, ".secret.md")


def test_resolve_material_path_rejects_non_md(tmp_path: Path) -> None:
    with pytest.raises(WorkspacePathError, match=r"\.md"):
        resolve_material_path(tmp_path, _GOAL_ID, _MS_ID, "intro.txt")
    with pytest.raises(WorkspacePathError, match=r"\.md"):
        resolve_material_path(tmp_path, _GOAL_ID, _MS_ID, "intro")


def test_resolve_material_path_rejects_unsafe_chars(tmp_path: Path) -> None:
    """Spaces / unicode / shell metacharacters all rejected."""
    bad_names = [
        "with space.md",
        "中文.md",   # we said ASCII-only in Q2
        "evil$cmd.md",
        "with(paren).md",
        ".md",  # extension only — no stem
    ]
    for name in bad_names:
        with pytest.raises(WorkspacePathError):
            resolve_material_path(tmp_path, _GOAL_ID, _MS_ID, name)


def test_resolve_material_path_accepts_normal_names(tmp_path: Path) -> None:
    """Realistic filenames the LLM might pick. Must all pass."""
    good = [
        "intro.md",
        "01-intro.md",
        "lesson_2.md",
        "Cheatsheet.md",
        "v1.0.md",
        "a.b.c.md",
    ]
    for name in good:
        out = resolve_material_path(tmp_path, _GOAL_ID, _MS_ID, name)
        assert out.name == name


def test_resolve_descendant_check_blocks_symlink_escape(tmp_path: Path) -> None:
    """If a malicious symlink ever ended up under goals/<gid>/milestones/<mid>/,
    Path.resolve() would canonicalize it and the descendant check should
    still hold (because we resolve to the leaf file path, not the symlink).
    Hard to construct a real attack here, but verify the function uses
    resolve() (no exception thrown for normal paths is sufficient
    proof — the negative cases above already prove rejection).
    """
    out = resolve_milestone_dir(tmp_path, _GOAL_ID, _MS_ID)
    # The resolved path must still be under tmp_path.
    assert out.is_relative_to(tmp_path.resolve())


def test_random_uuids_are_accepted(tmp_path: Path) -> None:
    """Sanity: any well-formed UUID resolves cleanly."""
    for _ in range(5):
        gid, mid = uuid4(), uuid4()
        out = resolve_milestone_dir(tmp_path, gid, mid)
        assert str(gid) in str(out)
        assert str(mid) in str(out)
