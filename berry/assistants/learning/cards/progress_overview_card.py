"""Progress overview card — full ROADMAP + module/atom progress at a glance.

Triggered (Q3=c, locked 2026-06-06):
  - User explicitly asks: ``@berry 进度`` / 「我学到哪了」 / 「ROADMAP」
  - Milestone events: module complete, topic complete, ROADMAP edited

NOT triggered:
  - Every progress.json write (too noisy)
  - Per-atom completion (use SUGGEST card's inline status instead)

Visual:

    ┌─ Redis · 1/6 模块 · 12/47 atom ────────────────────┐
    │ ✅ 01 概述与基础              88 分 (4/4)           │
    │ ▸ 02 数据结构与底层实现   进行中 (3/6)              │
    │   ✅ a1 SDS                  8.8 (1)               │
    │   ✅ a2 ziplist              8.0 (1)               │
    │   ▸ a3 quicklist  ← 当前(ASSESSING)               │
    │   ○ a4 dict 渐进式 rehash                           │
    │   ○ a5 intset                                       │
    │   ○ a6 zset 跳表 + dict                             │
    │ ○ 03 持久化与过期淘汰                                │
    │ ○ 04 高可用                                         │
    │ ○ 05a 缓存三连                                      │
    │ ○ 05b 热点 key                                      │
    └─────────────────────────────────────────────────────┘

We render the **current module fully expanded** (atoms shown), all other
modules collapsed to one line. This balances "show me the big picture" with
"don't drown me in 47 lines".
"""

from __future__ import annotations

import json
from typing import Any


def _atom_line(atom_id: str, atom_data: dict[str, Any], is_current: bool) -> str:
    status = atom_data.get("status", "pending")
    name = atom_data.get("name") or atom_id
    score = atom_data.get("score")
    attempts = atom_data.get("attempts", 0)

    if is_current:
        micro = atom_data.get("micro_state") or "进行中"
        return f"  ▸ {atom_id} {name}  ← 当前({micro})"

    if status == "done":
        score_part = f"{score:.1f}" if isinstance(score, (int, float)) else "—"
        attempt_part = f"({attempts})" if attempts > 1 else ""
        markers: list[str] = []
        if atom_data.get("self_advanced"):
            markers.append("self")
        if atom_data.get("needs_review"):
            markers.append("review")
        if atom_data.get("skipped"):
            markers.append("skip")
        marker_part = f" [{','.join(markers)}]" if markers else ""
        return f"  ✅ {atom_id} {name}  {score_part}{attempt_part}{marker_part}"

    return f"  ○ {atom_id} {name}"


def _module_line_collapsed(mod_id: str, mod_data: dict[str, Any]) -> str:
    status = mod_data.get("status", "pending")
    name = mod_data.get("name") or mod_id
    atoms = mod_data.get("atoms", {})
    total = len(atoms) or mod_data.get("atoms_total", 0)
    done = sum(1 for a in atoms.values() if a.get("status") == "done")

    if status == "done":
        score = mod_data.get("score")
        score_part = f" {score:.0f} 分" if isinstance(score, (int, float)) else ""
        return f"✅ {mod_id} {name}{score_part} ({done}/{total})"
    if status == "in_progress":
        return f"▸ {mod_id} {name}  进行中 ({done}/{total})"
    return f"○ {mod_id} {name}"


def _module_block_expanded(
    mod_id: str, mod_data: dict[str, Any], current_atom: str | None
) -> list[str]:
    """Module shown with all atoms listed below."""
    head = _module_line_collapsed(mod_id, mod_data)
    lines = [head]
    atoms = mod_data.get("atoms", {})
    for atom_id, atom_data in atoms.items():
        is_current = atom_id == current_atom
        lines.append(_atom_line(atom_id, atom_data, is_current))
    return lines


def build_progress_overview_card(
    *,
    topic: str,
    goal: str | None,
    modules: dict[str, dict[str, Any]],
    current_module: str | None,
    current_atom: str | None,
    started_at: str | None = None,
    last_active_at: str | None = None,
    total_active_minutes: int | None = None,
) -> str:
    """Build the progress overview card.

    Parameters
    ----------
    topic:
        Top-level topic name (e.g. "redis"), used in the header.
    goal:
        ``"easy"`` / ``"interview"`` / ``"deep"`` / ``None``. Shown in subtitle.
    modules:
        ``progress.json["modules"]`` shape:
        ``{<mod_id>: {name, status, score?, atoms: {<atom_id>: {...}}}}``.
        Order in iteration = display order; Python 3.7+ dicts preserve insertion.
    current_module / current_atom:
        Where the user is right now. The matching module is rendered fully
        expanded; siblings stay collapsed.
    started_at / last_active_at / total_active_minutes:
        Optional footer telemetry.

    Returns
    -------
    JSON string for ``msg_type=interactive``.
    """
    total_modules = len(modules)
    done_modules = sum(1 for m in modules.values() if m.get("status") == "done")
    total_atoms = sum(len(m.get("atoms", {})) for m in modules.values())
    done_atoms = sum(
        1
        for m in modules.values()
        for a in m.get("atoms", {}).values()
        if a.get("status") == "done"
    )

    title_suffix = ""
    if goal:
        goal_label = {"easy": "简单了解", "interview": "准备面试", "deep": "深入掌握"}.get(goal, goal)
        title_suffix = f" · {goal_label}"
    title = (
        f"📋 {topic}{title_suffix} · "
        f"{done_modules}/{total_modules} 模块 · {done_atoms}/{total_atoms} atom"
    )

    body_lines: list[str] = []
    for mod_id, mod_data in modules.items():
        if mod_id == current_module:
            body_lines.extend(_module_block_expanded(mod_id, mod_data, current_atom))
        else:
            body_lines.append(_module_line_collapsed(mod_id, mod_data))

    footer_parts: list[str] = []
    if total_active_minutes is not None:
        footer_parts.append(f"累计学习 {total_active_minutes} 分钟")
    if started_at:
        footer_parts.append(f"开始 {started_at[:10]}")
    if last_active_at:
        footer_parts.append(f"上次 {last_active_at[:16].replace('T', ' ')}")
    footer = " · ".join(footer_parts) if footer_parts else None

    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": "\n".join(body_lines)},
    ]
    if footer:
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": f"_{footer}_"})

    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {"width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "body": {"elements": elements},
    }
    return json.dumps(card, ensure_ascii=False)
