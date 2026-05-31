"""Integration tests for ScoreAttemptTool."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.attempt_repo import AttemptRepo
from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.assistants.learning.tools.learning.pose_question import PoseQuestionTool
from berry.assistants.learning.tools.learning.score_attempt import ScoreAttemptTool
from berry.core.db.repos.user_repo import UserRepo
from berry.core.tools.base import ToolContext


def _ctx(db_session: AsyncSession, user_id: UUID, data_root: Path) -> ToolContext:
    return ToolContext(
        session_id=uuid4(),
        user_id=user_id,
        db=db_session,
        data_root=data_root,
    )


async def _seed_attempt(
    db_session: AsyncSession, suffix: str, tmp_path: Path
) -> tuple[UUID, UUID]:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"score_{suffix}",
        display_name="Score Test",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    rows = await MilestoneRepo(db_session).insert_batch(g.id, [("ms", "")])
    raw = await PoseQuestionTool().execute(
        {
            "milestone_id": str(rows[0].id),
            "kind": "application",
            "question": "Q?",
        },
        _ctx(db_session, user.id, tmp_path),
    )
    return user.id, UUID(json.loads(raw)["attempt_id"])


@pytest.mark.asyncio
async def test_writes_answer_and_score(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, attempt_id = await _seed_attempt(db_session, "happy", tmp_path)
    raw = await ScoreAttemptTool().execute(
        {
            "attempt_id": str(attempt_id),
            "user_answer": "user wrote this",
            "score": 4,
            "reasoning": "mostly correct, missing edge cases",
            "reference_points": ["point a", "point b", "point c"],
        },
        _ctx(db_session, user_id, tmp_path),
    )
    payload = json.loads(raw)
    assert payload["score"] == 4
    assert payload["ok"] is True

    refreshed = await AttemptRepo(db_session).get_by_id(attempt_id)
    assert refreshed is not None
    assert refreshed.user_answer == "user wrote this"
    assert refreshed.score == 4
    assert refreshed.reasoning == "mostly correct, missing edge cases"
    assert refreshed.reference_points == ["point a", "point b", "point c"]


@pytest.mark.asyncio
async def test_score_out_of_range_rejected(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, attempt_id = await _seed_attempt(db_session, "range", tmp_path)
    for bad in (0, 6, -1, 99):
        with pytest.raises(ValueError, match=r"score"):
            await ScoreAttemptTool().execute(
                {
                    "attempt_id": str(attempt_id),
                    "user_answer": "x",
                    "score": bad,
                    "reasoning": "r",
                    "reference_points": ["a"],
                },
                _ctx(db_session, user_id, tmp_path),
            )


@pytest.mark.asyncio
async def test_empty_reasoning_rejected(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, attempt_id = await _seed_attempt(db_session, "empty_reason", tmp_path)
    with pytest.raises(ValueError, match="reasoning"):
        await ScoreAttemptTool().execute(
            {
                "attempt_id": str(attempt_id),
                "user_answer": "x",
                "score": 3,
                "reasoning": "   ",
                "reference_points": ["a"],
            },
            _ctx(db_session, user_id, tmp_path),
        )
