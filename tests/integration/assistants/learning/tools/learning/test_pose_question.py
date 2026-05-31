"""Integration tests for PoseQuestionTool."""

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
from berry.core.db.repos.user_repo import UserRepo
from berry.core.tools.base import ToolContext


def _ctx(db_session: AsyncSession, user_id: UUID, data_root: Path) -> ToolContext:
    return ToolContext(
        session_id=uuid4(),
        user_id=user_id,
        db=db_session,
        data_root=data_root,
    )


async def _seed(db_session: AsyncSession, suffix: str) -> tuple[UUID, UUID]:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"pose_q_{suffix}",
        display_name="Pose Q Test",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    rows = await MilestoneRepo(db_session).insert_batch(g.id, [("ms", "")])
    return user.id, rows[0].id


@pytest.mark.asyncio
async def test_application_question_persists(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, milestone_id = await _seed(db_session, "app")
    raw = await PoseQuestionTool().execute(
        {
            "milestone_id": str(milestone_id),
            "kind": "application",
            "question": "Explain StateGraph in one sentence.",
        },
        _ctx(db_session, user_id, tmp_path),
    )
    payload = json.loads(raw)
    attempt = await AttemptRepo(db_session).get_by_id(UUID(payload["attempt_id"]))
    assert attempt is not None
    assert attempt.kind == "application"
    assert attempt.question == "Explain StateGraph in one sentence."
    assert attempt.choices is None
    assert attempt.correct_index is None


@pytest.mark.asyncio
async def test_choice_question_persists_with_answers(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, milestone_id = await _seed(db_session, "choice")
    raw = await PoseQuestionTool().execute(
        {
            "milestone_id": str(milestone_id),
            "kind": "choice",
            "question": "Which is true?",
            "choices": ["A is wrong", "B is right", "C is wrong", "D is wrong"],
            "correct_index": 1,
        },
        _ctx(db_session, user_id, tmp_path),
    )
    payload = json.loads(raw)
    attempt = await AttemptRepo(db_session).get_by_id(UUID(payload["attempt_id"]))
    assert attempt is not None
    assert attempt.kind == "choice"
    assert attempt.choices == ["A is wrong", "B is right", "C is wrong", "D is wrong"]
    assert attempt.correct_index == 1


@pytest.mark.asyncio
async def test_choice_requires_4_options(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, milestone_id = await _seed(db_session, "bad_choices")
    with pytest.raises(ValueError, match="exactly 4"):
        await PoseQuestionTool().execute(
            {
                "milestone_id": str(milestone_id),
                "kind": "choice",
                "question": "?",
                "choices": ["A", "B"],
                "correct_index": 0,
            },
            _ctx(db_session, user_id, tmp_path),
        )


@pytest.mark.asyncio
async def test_choice_requires_correct_index(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, milestone_id = await _seed(db_session, "bad_idx")
    with pytest.raises(ValueError, match="correct_index"):
        await PoseQuestionTool().execute(
            {
                "milestone_id": str(milestone_id),
                "kind": "choice",
                "question": "?",
                "choices": ["A", "B", "C", "D"],
            },
            _ctx(db_session, user_id, tmp_path),
        )


@pytest.mark.asyncio
async def test_application_rejects_choices(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, milestone_id = await _seed(db_session, "app_rejects")
    with pytest.raises(ValueError, match="must not include"):
        await PoseQuestionTool().execute(
            {
                "milestone_id": str(milestone_id),
                "kind": "application",
                "question": "?",
                "choices": ["A", "B", "C", "D"],
            },
            _ctx(db_session, user_id, tmp_path),
        )


@pytest.mark.asyncio
async def test_unknown_milestone_raises(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    user_id, _ = await _seed(db_session, "ghost")
    with pytest.raises(ValueError, match="not found"):
        await PoseQuestionTool().execute(
            {
                "milestone_id": str(uuid4()),
                "kind": "application",
                "question": "?",
            },
            _ctx(db_session, user_id, tmp_path),
        )
