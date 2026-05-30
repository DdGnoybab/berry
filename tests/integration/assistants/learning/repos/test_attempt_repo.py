"""Integration tests for AttemptRepo."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from berry.assistants.learning.repos.attempt_repo import AttemptRepo
from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.core.db.repos.user_repo import UserRepo


async def _seed_milestone(db_session: AsyncSession, suffix: str) -> UUID:
    user = await UserRepo(db_session).create_or_get_by_external(
        external_source="cli",
        external_id=f"att_test_{suffix}",
        display_name=f"Att Test {suffix}",
    )
    g = await GoalRepo(db_session).create(
        user_id=user.id, title="t", workspace_path=f"goals/{suffix}"
    )
    rows = await MilestoneRepo(db_session).insert_batch(g.id, [("ms", "")])
    return rows[0].id


@pytest.mark.asyncio
async def test_create_application_attempt(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "app")
    repo = AttemptRepo(db_session)
    a = await repo.create(
        milestone_id=mid,
        kind="application",
        question="Explain StateGraph",
    )
    assert a.kind == "application"
    assert a.choices is None
    assert a.correct_index is None
    assert a.score is None


@pytest.mark.asyncio
async def test_create_choice_attempt(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "choice")
    repo = AttemptRepo(db_session)
    a = await repo.create(
        milestone_id=mid,
        kind="choice",
        question="Which is true?",
        choices=["A", "B", "C", "D"],
        correct_index=2,
    )
    assert a.kind == "choice"
    assert a.choices == ["A", "B", "C", "D"]
    assert a.correct_index == 2


@pytest.mark.asyncio
async def test_create_rejects_unknown_kind(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "kind")
    repo = AttemptRepo(db_session)
    with pytest.raises(ValueError, match="unknown attempt kind"):
        await repo.create(
            milestone_id=mid,
            kind="bogus",
            question="?",
        )


@pytest.mark.asyncio
async def test_set_answer_then_score(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "answer")
    repo = AttemptRepo(db_session)
    a = await repo.create(milestone_id=mid, kind="application", question="q")

    await repo.set_answer(a.id, "user wrote this")
    await repo.set_score(
        a.id,
        score=4,
        reasoning="mostly right",
        reference_points=["point a", "point b"],
    )

    refreshed = await repo.get_by_id(a.id)
    assert refreshed is not None
    assert refreshed.user_answer == "user wrote this"
    assert refreshed.score == 4
    assert refreshed.reasoning == "mostly right"
    assert refreshed.reference_points == ["point a", "point b"]


@pytest.mark.asyncio
async def test_set_score_rejects_out_of_range(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "score_range")
    repo = AttemptRepo(db_session)
    a = await repo.create(milestone_id=mid, kind="application", question="q")
    with pytest.raises(ValueError, match="score out of range"):
        await repo.set_score(a.id, score=0, reasoning="r", reference_points=[])
    with pytest.raises(ValueError, match="score out of range"):
        await repo.set_score(a.id, score=6, reasoning="r", reference_points=[])


@pytest.mark.asyncio
async def test_set_user_decision(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "decide")
    repo = AttemptRepo(db_session)
    a = await repo.create(milestone_id=mid, kind="application", question="q")
    await repo.set_decision(a.id, "next")

    refreshed = await repo.get_by_id(a.id)
    assert refreshed is not None
    assert refreshed.user_decision == "next"


@pytest.mark.asyncio
async def test_set_decision_rejects_unknown(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "decide_bad")
    repo = AttemptRepo(db_session)
    a = await repo.create(milestone_id=mid, kind="application", question="q")
    with pytest.raises(ValueError, match="unknown decision"):
        await repo.set_decision(a.id, "skip")


@pytest.mark.asyncio
async def test_list_by_milestone_oldest_first(db_session: AsyncSession) -> None:
    mid = await _seed_milestone(db_session, "list")
    repo = AttemptRepo(db_session)
    first = await repo.create(milestone_id=mid, kind="application", question="q1")
    second = await repo.create(milestone_id=mid, kind="application", question="q2")

    rows = await repo.list_by_milestone(mid)
    assert [r.id for r in rows] == [first.id, second.id]
