"""Path-scope guard for workspace tools.

The LLM picks ``goal_id`` / ``milestone_id`` / ``filename`` — none of these
inputs can be trusted. This module is the single place that turns those
inputs into a real filesystem path AND verifies the path stays inside
``data_root``. If anything looks off, raise ``WorkspacePathError`` and let
the runtime turn that into a ``ToolResultBlock(is_error=True, ...)`` for
the LLM to see.

Rules enforced:
1. ``filename`` must match ``[A-Za-z0-9_.-]+\\.md`` exactly — no slashes,
   no spaces, no leading dot, must end in ``.md``.
2. The resolved absolute path must be a descendant of ``data_root``. We
   use ``Path.resolve()`` to canonicalize symlinks and ``..`` segments.
3. The path layout is fixed:
   ``<data_root>/goals/<goal_id>/milestones/<milestone_id>/<filename>``.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from berry.domain.errors import BerryError

_FILENAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.md$")
_LEADING_DOT_RE = re.compile(r"^\.")


class WorkspacePathError(BerryError):
    """raised when LLM-supplied path inputs would escape the allowed scope."""


def resolve_milestone_dir(
    data_root: Path, goal_id: UUID, milestone_id: UUID
) -> Path:
    """Return the canonicalized milestone directory under ``data_root``.

    Raises ``WorkspacePathError`` if the resolved path escapes ``data_root``.
    Does NOT create the directory — callers create on demand with
    ``mkdir(parents=True, exist_ok=True)``.
    """
    target = (
        data_root
        / "goals"
        / str(goal_id)
        / "milestones"
        / str(milestone_id)
    ).resolve()
    root = data_root.resolve()
    _assert_descendant(target, root)
    return target


def resolve_material_path(
    data_root: Path,
    goal_id: UUID,
    milestone_id: UUID,
    filename: str,
) -> Path:
    """Same as ``resolve_milestone_dir`` plus a strict filename check.

    ``filename`` must be a single ``.md`` file with safe characters; we
    reject path separators, leading dots (avoid hidden files), and anything
    that doesn't look like ``foo-bar_baz.md``.
    """
    if "/" in filename or "\\" in filename:
        raise WorkspacePathError(
            f"filename {filename!r} contains a path separator"
        )
    if _LEADING_DOT_RE.match(filename):
        raise WorkspacePathError(
            f"filename {filename!r} starts with '.' (hidden files not allowed)"
        )
    if not _FILENAME_RE.match(filename):
        raise WorkspacePathError(
            f"filename {filename!r} must match [A-Za-z0-9_.-]+\\.md "
            "(ASCII letters/digits/underscore/dot/hyphen, ending in .md)"
        )
    return resolve_milestone_dir(data_root, goal_id, milestone_id) / filename


def _assert_descendant(target: Path, root: Path) -> None:
    """Raise WorkspacePathError unless ``target`` lives under ``root``.

    We use Path.is_relative_to (Python 3.9+) — symlinks have already been
    canonicalized by ``resolve()``.
    """
    if not target.is_relative_to(root):
        raise WorkspacePathError(
            f"resolved path {target} escapes data_root {root}"
        )
