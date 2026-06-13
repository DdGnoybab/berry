"""Compute a Project's learning progress purely from workspace files.

Files-as-truth (ADR-0004): we don't store progress in the DB. Each
``project.list`` recomputes it from ``.berry/progress.json`` —
cheap, always fresh, user-editable.

Returns ``None`` if the workspace doesn't have ``.berry/progress.json``
(uninitialized project — no plan yet).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from berry.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ProjectProgress:
    """Snapshot of a Project's learning progress.

    Field meanings:
      - ``phase``: ``"uninitialized"`` (no progress.json) /
                  ``"planning"`` (has file but 0 atoms — partial init) /
                  ``"learning"`` (has atoms, normal state) /
                  ``"done"`` (all atoms done).
      - ``percent``: 0-100, rounded to int. ``done_atoms / total_atoms * 100``.
      - ``done_atoms`` / ``total_atoms``: atom-level counters.
      - ``done_modules`` / ``total_modules``: module-level counters.
      - ``current_atom``: ``"<module>/<atom>"`` style, e.g. ``"02/a3"``.
      - ``topic``: human-readable, taken from ``progress.json``'s top-level ``topic``.
    """

    phase: str
    percent: int
    done_atoms: int = 0
    total_atoms: int = 0
    done_modules: int = 0
    total_modules: int = 0
    current_atom: str | None = None
    topic: str | None = None


def compute_progress(workspace_path: Path) -> ProjectProgress:
    """Read ``<workspace>/.berry/progress.json`` and derive progress stats.

    On missing / malformed file returns a safe default
    (``phase="uninitialized"``, percent=0). Never raises.
    """
    pj = workspace_path / ".berry" / "progress.json"
    if not pj.is_file():
        return ProjectProgress(phase="uninitialized", percent=0)

    try:
        data = json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "progress_json_read_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            path=str(pj),
        )
        return ProjectProgress(phase="uninitialized", percent=0)

    modules = data.get("modules") or {}
    total_modules = len(modules)
    # skipped 等价于 done — 用户主动判断「这块我会了 / 不学了」也是进度推进。
    # 不区分两者,UX 简洁:进度条动了就是走了。
    _DONE_STATUSES = {"done", "skipped"}
    done_modules = sum(
        1 for m in modules.values() if m.get("status") in _DONE_STATUSES
    )

    total_atoms = sum(
        len(m.get("atoms") or {}) for m in modules.values()
    )
    done_atoms = sum(
        1
        for m in modules.values()
        for a in (m.get("atoms") or {}).values()
        if a.get("status") in _DONE_STATUSES
    )

    if total_atoms == 0:
        phase = "planning"
        percent = 0
    elif done_atoms >= total_atoms:
        phase = "done"
        percent = 100
    else:
        phase = "learning"
        percent = round(done_atoms * 100 / total_atoms)

    current = data.get("current") or {}
    current_module = current.get("module")
    current_atom_id = current.get("atom")
    current_atom = (
        f"{current_module}/{current_atom_id}"
        if current_module and current_atom_id
        else current_atom_id
    )

    return ProjectProgress(
        phase=phase,
        percent=percent,
        done_atoms=done_atoms,
        total_atoms=total_atoms,
        done_modules=done_modules,
        total_modules=total_modules,
        current_atom=current_atom,
        topic=data.get("topic"),
    )
