"""ScoreAttemptTool — record the LLM's grading of a user answer.

The user's answer text gets persisted via AttemptRepo.set_answer first
(the LLM does that as a separate set_answer-like call? — no, we fold it
into score_attempt: the LLM passes the user_answer it observed, and the
tool writes both answer and score atomically).

Score is 1-5 with reasoning + reference_points (per Q3 brainstorm).
The user, not the LLM, decides what to do with the score (next/retry/reread).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from uuid import UUID

from berry.assistants.learning.repos.attempt_repo import AttemptRepo
from berry.core.tools.base import ToolContext


class ScoreAttemptTool:
    name: ClassVar[str] = "score_attempt"
    description: ClassVar[str] = (
        "Score a user's answer to a previously-posed question. Write the "
        "user_answer (verbatim from their last reply), the score (1-5), a "
        "1-2 sentence reasoning, and 2-5 reference_points the user could "
        "compare their answer against. Then narrate the outcome in your "
        "visible reply — the user reads your prose, not this tool's output."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "attempt_id": {
                "type": "string",
                "description": "UUID returned by pose_question for this question.",
            },
            "user_answer": {
                "type": "string",
                "description": "The user's answer, copied verbatim from their last message.",
            },
            "score": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": (
                    "1=way off; 2=mostly missing the point; 3=partial; "
                    "4=mostly correct, minor gaps; 5=fully correct."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "1-2 sentence why-this-score explanation.",
            },
            "reference_points": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 5,
                "description": "Key points a complete answer should hit.",
            },
        },
        "required": [
            "attempt_id",
            "user_answer",
            "score",
            "reasoning",
            "reference_points",
        ],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.db is None:
            raise RuntimeError("score_attempt requires a db session in ToolContext")

        attempt_id = UUID(str(args["attempt_id"]))
        score = int(args["score"])
        reasoning = str(args["reasoning"]).strip()
        reference_points = [str(p).strip() for p in args["reference_points"]]
        user_answer = str(args["user_answer"]).strip()
        if not reasoning:
            raise ValueError("reasoning must be non-empty")
        if not reference_points:
            raise ValueError("reference_points must be non-empty")

        repo = AttemptRepo(ctx.db)

        # Persist the user's answer first so it's recoverable even if
        # set_score later fails.
        if user_answer:
            await repo.set_answer(attempt_id, user_answer)

        await repo.set_score(
            attempt_id,
            score=score,
            reasoning=reasoning,
            reference_points=reference_points,
        )

        return json.dumps(
            {
                "attempt_id": str(attempt_id),
                "score": score,
                "ok": True,
            },
            ensure_ascii=False,
        )
