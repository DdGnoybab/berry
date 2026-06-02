"""TDD tests for progress_parser.py.

Parses PROGRESS.md (Berry Learning Loop's source-of-truth file) into a
structured ProgressSnapshot. Format spec lives in
docs/superpowers/specs/2026-06-01-learning-loop-product-design.md § 2.2.

Parser is intentionally tolerant: garbage in returns None (LLM falls back
to reading PROGRESS.md raw via read_file). Never crashes the prompt build.
"""

from __future__ import annotations

import pytest

from berry.assistants.learning.prompts.progress_parser import (
    Milestone,
    ProgressSnapshot,
    SmallGoal,
    parse_progress_md,
)


# ─── Happy path ────────────────────────────────────────────────────────────


def test_parses_minimal_progress() -> None:
    """Goal + 1 milestone + 0 small goals."""
    content = """\
# Redis 学习进度

> 最终目标: 深入理解 Redis,能应对深层追问

## 里程碑列表

### [pending] 1. 数据结构原理
- 完成判据: 能解释 5 个核心结构 + 各自性能权衡
- 小目标: (进入此里程碑时再拆,1-4 个)
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.goal == "深入理解 Redis,能应对深层追问"
    assert len(snap.milestones) == 1
    m = snap.milestones[0]
    assert m.index == 1
    assert m.title == "数据结构原理"
    assert m.status == "pending"
    assert m.criterion == "能解释 5 个核心结构 + 各自性能权衡"
    assert m.small_goals == []


def test_parses_milestone_with_small_goals() -> None:
    """Milestone with 4 small goals + scores → all parsed."""
    content = """\
# 学习进度

> 最终目标: 深入理解 Redis

### [in_progress] 1. 数据结构原理
- 完成判据: 能解释 5 个核心结构
- 小目标:
  - [done] 1.1 SDS — 设计原理与权衡 [9.5]
  - [in_progress] 1.2 ziplist / listpack — 紧凑结构的演进
  - [pending] 1.3 quicklist — List 的双层结构
  - [pending] 1.4 skiplist + dict — ZSet 的双数据结构协作
"""
    snap = parse_progress_md(content)
    assert snap is not None
    m = snap.milestones[0]
    assert len(m.small_goals) == 4
    sg1 = m.small_goals[0]
    assert sg1.index == "1.1"
    assert sg1.title == "SDS — 设计原理与权衡"
    assert sg1.status == "done"
    assert sg1.score == 9.5
    sg2 = m.small_goals[1]
    assert sg2.index == "1.2"
    assert sg2.status == "in_progress"
    assert sg2.score is None


# ─── Status enum ───────────────────────────────────────────────────────────


def test_parses_done_status() -> None:
    content = """\
> 最终目标: x
### [done] 1. y
- 完成判据: z
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.milestones[0].status == "done"


def test_parses_in_progress_status() -> None:
    content = """\
> 最终目标: x
### [in_progress] 1. y
- 完成判据: z
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.milestones[0].status == "in_progress"


def test_parses_skipped_status() -> None:
    content = """\
> 最终目标: x
### [skipped] 1. y
- 完成判据: z
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.milestones[0].status == "skipped"


# ─── Multi-milestone ───────────────────────────────────────────────────────


def test_parses_multiple_milestones_in_order() -> None:
    """6 milestones, mixed statuses → all parsed in declared order."""
    content = """\
> 最终目标: 深入理解 Redis

### [done] 1. 数据结构原理
- 完成判据: c1
### [in_progress] 2. 过期与内存
- 完成判据: c2
### [pending] 3. 持久化
- 完成判据: c3
### [pending] 4. 主从+哨兵
- 完成判据: c4
### [pending] 5. Lua 脚本
- 完成判据: c5
### [pending] 6. 实战与坑
- 完成判据: c6
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert len(snap.milestones) == 6
    assert [m.index for m in snap.milestones] == [1, 2, 3, 4, 5, 6]
    assert snap.milestones[0].status == "done"
    assert snap.milestones[1].status == "in_progress"
    assert all(m.status == "pending" for m in snap.milestones[2:])


# ─── Active milestone / small goal accessors ───────────────────────────────


def test_active_milestone_returns_in_progress_one() -> None:
    content = """\
> 最终目标: x
### [done] 1. a
- 完成判据: c1
### [in_progress] 2. b
- 完成判据: c2
### [pending] 3. c
- 完成判据: c3
"""
    snap = parse_progress_md(content)
    assert snap is not None
    active = snap.active_milestone
    assert active is not None
    assert active.index == 2
    assert active.title == "b"


def test_active_milestone_returns_none_when_all_done() -> None:
    content = """\
> 最终目标: x
### [done] 1. a
- 完成判据: c1
### [done] 2. b
- 完成判据: c2
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.active_milestone is None


def test_active_small_goal_returns_in_progress_one() -> None:
    content = """\
> 最终目标: x
### [in_progress] 1. a
- 完成判据: c
- 小目标:
  - [done] 1.1 first [9.0]
  - [in_progress] 1.2 second
  - [pending] 1.3 third
"""
    snap = parse_progress_md(content)
    assert snap is not None
    sg = snap.active_small_goal
    assert sg is not None
    assert sg.index == "1.2"
    assert sg.title == "second"


def test_active_small_goal_returns_none_when_milestone_has_none() -> None:
    """Milestone is in_progress but its small goals haven't been decomposed."""
    content = """\
> 最终目标: x
### [in_progress] 1. a
- 完成判据: c
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.active_small_goal is None


# ─── Average score ─────────────────────────────────────────────────────────


def test_average_score_excludes_pending_small_goals() -> None:
    content = """\
> 最终目标: x
### [in_progress] 1. a
- 完成判据: c
- 小目标:
  - [done] 1.1 a [9.0]
  - [done] 1.2 b [8.0]
  - [in_progress] 1.3 c
  - [pending] 1.4 d
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.average_score == 8.5


def test_average_score_returns_none_when_nothing_done() -> None:
    content = """\
> 最终目标: x
### [in_progress] 1. a
- 完成判据: c
- 小目标:
  - [in_progress] 1.1 a
  - [pending] 1.2 b
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.average_score is None


def test_milestone_score_averages_done_small_goal_scores() -> None:
    content = """\
> 最终目标: x
### [in_progress] 1. a
- 完成判据: c
- 小目标:
  - [done] 1.1 a [10.0]
  - [done] 1.2 b [8.0]
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.milestones[0].score == 9.0


# ─── Edge cases ────────────────────────────────────────────────────────────


def test_returns_none_for_empty_content() -> None:
    assert parse_progress_md("") is None


def test_returns_none_for_no_goal_line() -> None:
    """Content without `> 最终目标:` line is treated as un-parseable."""
    content = """\
# Some heading
### [pending] 1. milestone
- 完成判据: c
"""
    assert parse_progress_md(content) is None


def test_returns_snapshot_with_no_milestones_when_only_goal() -> None:
    content = """\
> 最终目标: 深入理解 Redis

(还没拆里程碑)
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.goal == "深入理解 Redis"
    assert snap.milestones == []


def test_handles_completion_judgement_line() -> None:
    """The `- 完成判据: xxx` line is captured in milestone.criterion."""
    content = """\
> 最终目标: x
### [pending] 1. milestone
- 完成判据: 能解释 N 件事
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.milestones[0].criterion == "能解释 N 件事"


def test_ignores_unrelated_text_between_milestones() -> None:
    """Random user-written paragraphs between milestones don't break parsing."""
    content = """\
> 最终目标: x

I'm experimenting with this format.

### [done] 1. a
- 完成判据: c1

(Some user musings about how the loop is going.)

### [in_progress] 2. b
- 完成判据: c2
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert len(snap.milestones) == 2


def test_milestone_without_score_brackets() -> None:
    """Milestone without trailing [score/10] still parses."""
    content = """\
> 最终目标: x
### [in_progress] 1. a
- 完成判据: c
"""
    snap = parse_progress_md(content)
    assert snap is not None
    assert snap.milestones[0].title == "a"
    assert snap.milestones[0].score is None


def test_small_goal_without_score_parses() -> None:
    content = """\
> 最终目标: x
### [in_progress] 1. a
- 完成判据: c
- 小目标:
  - [pending] 1.1 a
"""
    snap = parse_progress_md(content)
    assert snap is not None
    sg = snap.milestones[0].small_goals[0]
    assert sg.title == "a"
    assert sg.score is None
