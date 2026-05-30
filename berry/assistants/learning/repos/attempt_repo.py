"""Repository for the `attempts` table."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from berry.core.db.models import Attempt


class AttemptRepo:
    """Data-access layer for Attempt rows.

    Attempts are append-only event records: create fills required fields,
    and subsequent set_* methods fill in the remaining fields incrementally
    as the attempt progresses (answer → score → decision).
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        milestone_id: UUID,
        kind: str,
        question: str,
        choices: list[str] | None = None,
        correct_index: int | None = None,
    ) -> Attempt:
        """Create a new attempt for a milestone.

        Args:
            milestone_id: The milestone this attempt belongs to.
            kind: Either "application" (open-ended) or "choice" (multiple choice).
            question: The question text presented to the user.
            choices: For "choice" kind, the list of answer options.
            correct_index: For "choice" kind, the 0-based index of the correct option.

        Returns:
            The newly created and refreshed Attempt row.

        Raises:
            ValueError: If kind is not "application" or "choice".
        """
        if kind not in ("application", "choice"):
            raise ValueError(f"unknown attempt kind: {kind!r}")
        row = Attempt(
            milestone_id=milestone_id,
            kind=kind,
            question=question,
            choices=choices,
            correct_index=correct_index,
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def get_by_id(self, attempt_id: UUID) -> Attempt | None:
        """Fetch a single attempt by primary key.

        Args:
            attempt_id: The UUID primary key.

        Returns:
            The Attempt row, or None if not found.
        """
        result = await self._db.execute(
            select(Attempt).where(Attempt.id == attempt_id)
        )
        return result.scalar_one_or_none()

    async def set_answer(self, attempt_id: UUID, user_answer: str) -> None:
        """Record the user's answer text.

        Args:
            attempt_id: The UUID of the attempt to update.
            user_answer: The user's response to the question.
        """
        await self._db.execute(
            update(Attempt)
            .where(Attempt.id == attempt_id)
            .values(user_answer=user_answer)
        )
        await self._db.commit()

    async def set_score(
        self,
        attempt_id: UUID,
        *,
        score: int,
        reasoning: str,
        reference_points: list[str],
    ) -> None:
        """Record the LLM-evaluated score and feedback.

        Args:
            attempt_id: The UUID of the attempt to update.
            score: Integer score in [1, 5].
            reasoning: The LLM's explanation of the score.
            reference_points: Key points from the ideal answer.

        Raises:
            ValueError: If score is outside [1, 5].
        """
        if not 1 <= score <= 5:
            raise ValueError(f"score out of range [1,5]: {score}")
        await self._db.execute(
            update(Attempt)
            .where(Attempt.id == attempt_id)
            .values(
                score=score,
                reasoning=reasoning,
                reference_points=reference_points,
            )
        )
        await self._db.commit()

    async def set_decision(self, attempt_id: UUID, decision: str) -> None:
        """Record the user's next-step decision after reviewing their score.

        Args:
            attempt_id: The UUID of the attempt to update.
            decision: One of "next" (move on), "retry" (try again),
                or "reread" (go back to the material).

        Raises:
            ValueError: If decision is not one of the accepted values.
        """
        if decision not in ("next", "retry", "reread"):
            raise ValueError(f"unknown decision: {decision!r}")
        await self._db.execute(
            update(Attempt)
            .where(Attempt.id == attempt_id)
            .values(user_decision=decision)
        )
        await self._db.commit()

    async def list_by_milestone(self, milestone_id: UUID) -> list[Attempt]:
        """Return all attempts for a milestone ordered oldest first.

        Args:
            milestone_id: The milestone whose attempts to list.

        Returns:
            List of Attempt rows in insertion order.
        """
        result = await self._db.execute(
            select(Attempt)
            .where(Attempt.milestone_id == milestone_id)
            .order_by(Attempt.created_at.asc(), Attempt.id.asc())
        )
        return list(result.scalars().all())
