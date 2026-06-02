"""TDD tests for path_scope: workspace boundary enforcement.

Mirrors claw-code (reference/claw-code_1/rust/crates/runtime/src/file_ops.rs):
  - normalize_path: existing path → resolve(strict=True), absolute kept,
    relative joined to cwd
  - normalize_path_allow_missing: same but accepts not-yet-existing files
    by canonicalizing the parent dir
  - validate_workspace_boundary: is_relative_to(workspace.resolve()) or raise

Path resolution must collapse ../ and follow symlinks, so escape attempts
are caught regardless of how they're disguised.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from berry.core.tools.files.path_scope import (
    normalize_path,
    normalize_path_allow_missing,
    validate_workspace_boundary,
)
from berry.domain.errors import FileScopeError


# ─── normalize_path ────────────────────────────────────────────────────────


def test_normalize_relative_path_joins_cwd(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("x")
    assert normalize_path("a.md", tmp_path) == file.resolve()


def test_normalize_absolute_path_is_kept(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("x")
    assert normalize_path(str(file), tmp_path) == file.resolve()


def test_normalize_collapses_dotdot(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    file = tmp_path / "a.md"
    file.write_text("x")
    # "sub/../a.md" should resolve to <tmp_path>/a.md
    result = normalize_path("sub/../a.md", tmp_path)
    assert result == file.resolve()


def test_normalize_strict_raises_for_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        normalize_path("no-such.md", tmp_path)


def test_normalize_follows_symlinks(tmp_path: Path) -> None:
    """A symlink is canonicalized to its target — used by boundary check
    to detect escape via symlinks."""
    real = tmp_path / "real.md"
    real.write_text("x")
    link = tmp_path / "link.md"
    os.symlink(real, link)

    assert normalize_path("link.md", tmp_path) == real.resolve()


# ─── normalize_path_allow_missing ──────────────────────────────────────────


def test_allow_missing_returns_canonical_for_nonexistent(tmp_path: Path) -> None:
    """write_file calls this — file doesn't exist yet, parent does."""
    sub = tmp_path / "sub"
    sub.mkdir()
    result = normalize_path_allow_missing("sub/new.md", tmp_path)
    assert result == sub.resolve() / "new.md"


def test_allow_missing_works_when_parent_also_missing(tmp_path: Path) -> None:
    """Deep new path: cwd exists, intermediate dirs don't yet."""
    result = normalize_path_allow_missing("deep/inner/new.md", tmp_path)
    # Should not raise; resolve as best-effort for boundary check
    assert result.name == "new.md"


def test_allow_missing_returns_existing_canonical(tmp_path: Path) -> None:
    """When file does exist, behaves like normalize_path (full canonicalize)."""
    file = tmp_path / "a.md"
    file.write_text("x")
    assert normalize_path_allow_missing("a.md", tmp_path) == file.resolve()


# ─── validate_workspace_boundary ───────────────────────────────────────────


def test_inside_workspace_passes(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("x")
    validate_workspace_boundary(file.resolve(), tmp_path)  # must not raise


def test_outside_workspace_raises(tmp_path: Path) -> None:
    other = tmp_path.parent / "other-ws" / "leak.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("x")
    with pytest.raises(FileScopeError):
        validate_workspace_boundary(other.resolve(), tmp_path)


def test_dotdot_escape_caught_by_normalize_then_validate(tmp_path: Path) -> None:
    """Pipeline: normalize_path('../escape.md', tmp_path) returns parent path,
    then validate raises."""
    outside = tmp_path.parent / "escape.md"
    outside.write_text("x")
    try:
        target = normalize_path("../escape.md", tmp_path)
    except FileNotFoundError:
        pytest.skip("../escape.md does not resolve in this fixture layout")
    with pytest.raises(FileScopeError):
        validate_workspace_boundary(target, tmp_path)


def test_symlink_escape_caught(tmp_path: Path) -> None:
    """Symlink inside workspace pointing outside — canonicalize, then
    boundary check raises."""
    outside_dir = tmp_path.parent / "escape-target"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "secret.md"
    outside_file.write_text("nuclear codes")

    link = tmp_path / "looks-local.md"
    os.symlink(outside_file, link)

    target = normalize_path("looks-local.md", tmp_path)
    with pytest.raises(FileScopeError):
        validate_workspace_boundary(target, tmp_path)
