"""Workspace boundary enforcement for the file tools.

Mirrors claw-code (reference/claw-code_1/rust/crates/runtime/src/file_ops.rs):
  - normalize_path                — strict resolve, file must exist
  - normalize_path_allow_missing  — write_file uses this; file may not exist
  - validate_workspace_boundary   — is_relative_to check after canonicalize

Always run normalize_* first, then validate. Any path containing ``..`` or
symlinks is canonicalized, so escape attempts surface as boundary violations
regardless of how they were disguised.
"""

from __future__ import annotations

from pathlib import Path

from berry.domain.errors import FileScopeError


def normalize_path(path: str, cwd: Path) -> Path:
    """Resolve ``path`` to an absolute, canonical Path. The file must exist.

    Absolute paths are kept as-is before resolve(); relative paths are joined
    to ``cwd``. ``Path.resolve(strict=True)`` raises FileNotFoundError when
    any component is missing — write_file callers should use
    :func:`normalize_path_allow_missing` instead.

    Mirrors ``normalize_path`` in file_ops.rs:644.
    """
    candidate = Path(path) if Path(path).is_absolute() else cwd / path
    return candidate.resolve(strict=True)


def normalize_path_allow_missing(path: str, cwd: Path) -> Path:
    """Resolve ``path`` even if the target file doesn't exist yet.

    If the full path exists, returns its canonical form. Otherwise canonicalizes
    the longest existing prefix and reattaches the missing tail components.

    Mirrors ``normalize_path_allow_missing`` in file_ops.rs:653.
    """
    candidate = Path(path) if Path(path).is_absolute() else cwd / path
    try:
        return candidate.resolve(strict=True)
    except FileNotFoundError:
        pass

    # Walk up until we find an existing ancestor, canonicalize it, then
    # reattach the missing tail. This handles the case where multiple parent
    # directories don't exist yet (write_file does mkdir(parents=True) later).
    missing_parts: list[str] = []
    cursor = candidate
    while True:
        parent = cursor.parent
        if parent == cursor:
            # Reached filesystem root without finding an existing ancestor.
            return candidate
        try:
            canonical_ancestor = parent.resolve(strict=True)
        except FileNotFoundError:
            missing_parts.append(cursor.name)
            cursor = parent
            continue
        # Build back: canonical_ancestor / cursor.name / ...missing_parts (reverse)
        result = canonical_ancestor / cursor.name
        for part in reversed(missing_parts):
            result = result / part
        return result


def validate_workspace_boundary(absolute: Path, workspace: Path) -> None:
    """Raise :class:`FileScopeError` unless ``absolute`` lives under ``workspace``.

    Both paths are canonicalized via ``resolve()`` before comparison so symlinks
    and ``..`` segments cannot disguise an escape.

    Mirrors ``validate_workspace_boundary`` in file_ops.rs:42.
    """
    workspace_resolved = workspace.resolve()
    absolute_resolved = absolute.resolve() if absolute.exists() else absolute
    if not absolute_resolved.is_relative_to(workspace_resolved):
        raise FileScopeError(
            f"path {absolute_resolved} escapes workspace boundary "
            f"{workspace_resolved}"
        )


__all__ = [
    "normalize_path",
    "normalize_path_allow_missing",
    "validate_workspace_boundary",
]
