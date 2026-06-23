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
from typing import Any

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


def _normalize_modules(raw: Any) -> list[dict[str, Any]]:
    """Coerce ``progress.json["modules"]`` to a list of dict modules.

    Tolerates both the current ``{mod_id: mod_obj}`` shape and the legacy
    ``[mod_obj, ...]`` shape that some old / LLM-written files still use.
    Anything else (None, non-dict entries, ...) is dropped silently —
    callers prefer ``phase=uninitialized`` over a partial / wrong percent.
    """
    if isinstance(raw, dict):
        return [v for v in raw.values() if isinstance(v, dict)]
    if isinstance(raw, list):
        return [v for v in raw if isinstance(v, dict)]
    return []


def _atoms_of(module: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a module's atoms as a list, regardless of dict/list shape."""
    raw = module.get("atoms")
    if isinstance(raw, dict):
        return [v for v in raw.values() if isinstance(v, dict)]
    if isinstance(raw, list):
        return [v for v in raw if isinstance(v, dict)]
    return []


def compute_progress(workspace_path: Path) -> ProjectProgress:
    """Read ``<workspace>/.berry/progress.json`` and derive progress stats.

    On missing / malformed file returns a safe default
    (``phase="uninitialized"``, percent=0). Never raises.
    """
    pj = workspace_path / ".berry" / "progress.json"
    if not pj.is_file():
        return ProjectProgress(phase="uninitialized", percent=0)

    try:
        return _compute_progress_inner(pj)
    except Exception as exc:  # 兜底:坏 schema 不能拖垮 list_projects
        logger.warning(
            "progress_json_compute_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            path=str(pj),
            exc_info=True,
        )
        return ProjectProgress(phase="uninitialized", percent=0)


def _compute_progress_inner(pj: Path) -> ProjectProgress:
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

    # modules 历史上有两种形态:
    #   - dict[mod_id, mod_obj] —— 当前 schema
    #   - list[mod_obj]         —— 早期形态,LLM 仍偶发会写出来
    # 这里统一规整成 list[mod_obj] 处理,不挑形态。
    modules = _normalize_modules(data.get("modules"))
    total_modules = len(modules)
    # 三种"已结束"状态:
    #   done       — 历史叫法
    #   completed  — LLM prompt 教的叫法,实际写文件就是这个
    #   skipped    — 用户主动跳过,UX 上等价于完成
    # 三个一律算结束,UX 上"进度条动了就是走了"。
    _DONE_STATUSES = {"done", "completed", "skipped"}
    done_modules = sum(
        1 for m in modules if m.get("status") in _DONE_STATUSES
    )

    total_atoms = sum(
        len(_atoms_of(m)) for m in modules
    )
    # atom 算 done 的两种情况:
    #   1. atom 本身 status in _DONE_STATUSES — 正常路径
    #   2. atom 所在 module 的 status in _DONE_STATUSES — 兜底:LLM
    #      改文件时只改了 module 外层、忘了同步 atom 的常见 bug。
    #      module 整个被标完成时,里面的 atom 不可能还"没完成"。
    done_atoms = sum(
        1
        for m in modules
        for a in _atoms_of(m)
        if a.get("status") in _DONE_STATUSES
        or m.get("status") in _DONE_STATUSES
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
