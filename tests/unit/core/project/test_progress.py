"""Tests for compute_progress."""

from __future__ import annotations

import json
from pathlib import Path

from berry.core.project.progress import compute_progress


def _write_progress(workspace: Path, payload: dict) -> None:
    berry = workspace / ".berry"
    berry.mkdir(parents=True, exist_ok=True)
    (berry / "progress.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_uninitialized_when_no_progress_json(tmp_path: Path) -> None:
    p = compute_progress(tmp_path)
    assert p.phase == "uninitialized"
    assert p.percent == 0
    assert p.total_atoms == 0


def test_planning_phase_when_no_atoms(tmp_path: Path) -> None:
    _write_progress(tmp_path, {"topic": "Redis", "modules": {}})
    p = compute_progress(tmp_path)
    assert p.phase == "planning"
    assert p.percent == 0


def test_learning_phase_partial_atoms(tmp_path: Path) -> None:
    _write_progress(tmp_path, {
        "topic": "Redis",
        "current": {"module": "01-overview", "atom": "a2"},
        "modules": {
            "01-overview": {
                "name": "概述",
                "status": "in_progress",
                "atoms": {
                    "a1": {"name": "x", "status": "done"},
                    "a2": {"name": "y", "status": "pending"},
                },
            },
            "02-data": {
                "name": "数据",
                "status": "pending",
                "atoms": {
                    "a1": {"name": "z", "status": "pending"},
                    "a2": {"name": "w", "status": "pending"},
                },
            },
        },
    })
    p = compute_progress(tmp_path)
    assert p.phase == "learning"
    assert p.total_atoms == 4
    assert p.done_atoms == 1
    assert p.percent == 25
    assert p.current_atom == "01-overview/a2"
    assert p.topic == "Redis"


def test_done_phase(tmp_path: Path) -> None:
    _write_progress(tmp_path, {
        "topic": "X",
        "modules": {
            "01-x": {
                "name": "x",
                "status": "done",
                "atoms": {"a1": {"name": "x", "status": "done"}},
            }
        },
    })
    p = compute_progress(tmp_path)
    assert p.phase == "done"
    assert p.percent == 100


def test_malformed_json_returns_uninitialized(tmp_path: Path) -> None:
    berry = tmp_path / ".berry"
    berry.mkdir()
    (berry / "progress.json").write_text("not json", encoding="utf-8")
    p = compute_progress(tmp_path)
    assert p.phase == "uninitialized"
    assert p.percent == 0


def test_module_count_independent_from_atoms(tmp_path: Path) -> None:
    _write_progress(tmp_path, {
        "modules": {
            "m1": {"status": "done", "atoms": {"a1": {"status": "done"}}},
            "m2": {"status": "in_progress", "atoms": {"a1": {"status": "done"}, "a2": {"status": "pending"}}},
            "m3": {"status": "pending", "atoms": {}},
        }
    })
    p = compute_progress(tmp_path)
    assert p.total_modules == 3
    assert p.done_modules == 1
    assert p.total_atoms == 3
    assert p.done_atoms == 2


def test_skipped_atom_counts_as_done(tmp_path: Path) -> None:
    """用户跳过的 atom 跟 done 等价 — 进度条该往前。

    回归用例:redis 学习里跳过 module-01 / module-02 一共 10 atoms,
    但 done_atoms 之前算成 0,前端进度条不动。
    """
    _write_progress(tmp_path, {
        "topic": "Redis",
        "current": {"module": "03-persistence", "atom": "a1"},
        "modules": {
            "01": {
                "name": "概述",
                "status": "skipped",
                "atoms": {
                    "a1": {"status": "skipped"},
                    "a2": {"status": "skipped"},
                    "a3": {"status": "skipped"},
                    "a4": {"status": "skipped"},
                },
            },
            "02": {
                "name": "数据类型",
                "status": "skipped",
                "atoms": {
                    "a1": {"status": "skipped"},
                    "a2": {"status": "skipped"},
                    "a3": {"status": "skipped"},
                    "a4": {"status": "skipped"},
                    "a5": {"status": "skipped"},
                    "a6": {"status": "skipped"},
                },
            },
            "03": {
                "name": "持久化",
                "status": "in_progress",
                "atoms": {
                    "a1": {"status": "pending"},
                    "a2": {"status": "pending"},
                },
            },
        },
    })
    p = compute_progress(tmp_path)
    assert p.total_atoms == 12
    # 4 skipped + 6 skipped + 0 done = 10 进度
    assert p.done_atoms == 10
    # done modules: 2 skipped 都该算
    assert p.done_modules == 2
    # 10 / 12 = 83
    assert p.percent == 83
    assert p.phase == "learning"


def test_mixed_done_and_skipped(tmp_path: Path) -> None:
    """done 和 skipped 都算进度,加在一起。"""
    _write_progress(tmp_path, {
        "modules": {
            "m1": {
                "status": "done",
                "atoms": {
                    "a1": {"status": "done"},
                    "a2": {"status": "skipped"},
                },
            },
            "m2": {
                "status": "in_progress",
                "atoms": {
                    "a1": {"status": "skipped"},
                    "a2": {"status": "pending"},
                },
            },
        }
    })
    p = compute_progress(tmp_path)
    assert p.total_atoms == 4
    assert p.done_atoms == 3  # 1 done + 2 skipped
    assert p.percent == 75
