"""Parse PROGRESS.md (Berry Learning Loop's source of truth) into a snapshot.

Format spec:
  docs/superpowers/specs/2026-06-01-learning-loop-product-design.md § 2.2

Tolerance philosophy: garbage in returns ``None`` rather than raising —
the LLM falls back to reading PROGRESS.md raw and figuring it out itself.
The parser must NEVER crash the prompt build pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

Status = Literal["pending", "in_progress", "done", "skipped"]
_STATUSES = "pending|in_progress|done|skipped"


# ─── data classes ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SmallGoal:
    """An entry under a milestone."""

    index: str            # "1.1" / "1.2" / ...
    title: str            # "SDS — 设计原理与权衡"
    status: Status
    score: float | None = None  # 平均分,None = 还没测过


@dataclass(frozen=True)
class Milestone:
    """One milestone in PROGRESS.md."""

    index: int
    title: str
    status: Status
    criterion: str | None = None
    small_goals: list[SmallGoal] = field(default_factory=list)
    score: float | None = None  # 综合分(已 done 小目标均分,或 H3 行手写值)


@dataclass(frozen=True)
class ProgressSnapshot:
    """Parsed PROGRESS.md."""

    goal: str
    created_at: str | None = None
    milestones: list[Milestone] = field(default_factory=list)

    @property
    def active_milestone(self) -> Milestone | None:
        """The single [in_progress] milestone, or None."""
        for m in self.milestones:
            if m.status == "in_progress":
                return m
        return None

    @property
    def active_small_goal(self) -> SmallGoal | None:
        """The single [in_progress] small goal across all milestones, or None."""
        m = self.active_milestone
        if m is None:
            return None
        for sg in m.small_goals:
            if sg.status == "in_progress":
                return sg
        return None

    @property
    def average_score(self) -> float | None:
        """Avg of all [done] small-goal scores, or None if nothing done."""
        scores = [
            sg.score
            for m in self.milestones
            for sg in m.small_goals
            if sg.status == "done" and sg.score is not None
        ]
        return sum(scores) / len(scores) if scores else None


# ─── regex patterns ────────────────────────────────────────────────────────

# 顶层「最终目标:xxx」行(blockquote)
_GOAL_RE = re.compile(r"^>\s*最终目标:\s*(.+)$", re.MULTILINE)

# 里程碑 H3:### [status] N. title  [optional N.N/10]
_MILESTONE_RE = re.compile(
    rf"^###\s+\[({_STATUSES})\]\s+(\d+)\.\s+(.+?)"
    r"(?:\s+\[(\d+(?:\.\d+)?)/10\])?\s*$",
    re.MULTILINE,
)

# 小目标 bullet:缩进 - [status] N.M title [optional N.N]
# 题外注:title 可以是「主标题 — 副标题」,需要在末尾贪婪剥离 score 块
_SMALL_GOAL_RE = re.compile(
    rf"^\s+-\s+\[({_STATUSES})\]\s+(\d+\.\d+)\s+(.+?)"
    r"(?:\s+\[(\d+(?:\.\d+)?)\])?\s*$",
    re.MULTILINE,
)

# 「完成判据:xxx」行
_CRITERION_RE = re.compile(r"^\s*-\s*完成判据:\s*(.+)$", re.MULTILINE)


# ─── public entry ──────────────────────────────────────────────────────────


def parse_progress_md(content: str) -> ProgressSnapshot | None:
    """Parse PROGRESS.md content into a ProgressSnapshot.

    Returns None when content is empty, missing the goal line, or otherwise
    un-parseable. Callers should treat None as "no progress data" and let
    the LLM read PROGRESS.md raw if it wants details.
    """
    if not content.strip():
        return None

    goal_match = _GOAL_RE.search(content)
    if goal_match is None:
        return None
    goal = goal_match.group(1).strip()

    milestone_matches = list(_MILESTONE_RE.finditer(content))
    if not milestone_matches:
        return ProgressSnapshot(goal=goal, milestones=[])

    milestones: list[Milestone] = []
    for i, m_match in enumerate(milestone_matches):
        slice_start = m_match.start()
        slice_end = (
            milestone_matches[i + 1].start()
            if i + 1 < len(milestone_matches)
            else len(content)
        )
        block = content[slice_start:slice_end]

        status_str, idx_str, title, score_str = m_match.groups()

        criterion_match = _CRITERION_RE.search(block)
        criterion = criterion_match.group(1).strip() if criterion_match else None

        small_goals: list[SmallGoal] = []
        for sg_match in _SMALL_GOAL_RE.finditer(block):
            sg_status, sg_idx, sg_title, sg_score_str = sg_match.groups()
            small_goals.append(
                SmallGoal(
                    index=sg_idx,
                    title=sg_title.strip(),
                    status=sg_status,  # type: ignore[arg-type]
                    score=float(sg_score_str) if sg_score_str else None,
                )
            )

        # Milestone score: prefer averaged done-small-goal scores, else
        # fall back to the H3-line score if the user wrote one.
        done_scores = [
            sg.score for sg in small_goals if sg.status == "done" and sg.score is not None
        ]
        if done_scores:
            milestone_score: float | None = sum(done_scores) / len(done_scores)
        else:
            milestone_score = float(score_str) if score_str else None

        milestones.append(
            Milestone(
                index=int(idx_str),
                title=title.strip(),
                status=status_str,  # type: ignore[arg-type]
                criterion=criterion,
                small_goals=small_goals,
                score=milestone_score,
            )
        )

    return ProgressSnapshot(goal=goal, milestones=milestones)


__all__ = [
    "Milestone",
    "ProgressSnapshot",
    "SmallGoal",
    "Status",
    "parse_progress_md",
]
