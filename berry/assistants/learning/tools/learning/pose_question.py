"""PoseQuestionTool — record one question (application or choice) to attempts.

Per Q2 brainstorm: the LLM also speaks the question text out loud in its
reply (so the user sees it natively). This tool exists to (1) persist the
question for audit / analytics and (2) hand the LLM a stable attempt_id
to reference in the next score_attempt call.

Two question kinds:
- ``application``  open-ended; user types prose, LLM grades 1-5
- ``choice``       4 options, exactly one correct; user types A/B/C/D or the option text

The tool does NOT echo the question to the user — that's the LLM's job in
its visible reply. The tool only writes a row.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from uuid import UUID

from berry.assistants.learning.repos.attempt_repo import AttemptRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.core.tools.base import ToolContext


class PoseQuestionTool:
    name: ClassVar[str] = "pose_question"
    description: ClassVar[str] = (
        "Record a question for the current milestone. Speak the question "
        "text in your visible reply BEFORE calling this tool — the user "
        "reads your prose, not this tool's input. Use kind='application' "
        "for open-ended questions (default) and kind='choice' for short "
        "concept-disambiguation MCQs (exactly 4 options)."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "milestone_id": {
                "type": "string",
                "description": (
                    "UUID of the milestone the question belongs to "
                    "(usually the current_milestone_id from the system prompt)."
                ),
            },
            "kind": {
                "enum": ["application", "choice"],
                "description": "application = open-ended; choice = MCQ.",
            },
            "question": {
                "type": "string",
                "description": (
                    "The question text. SAME text you said to the user — "
                    "this is the canonical record."
                ),
            },
            "choices": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 4,
                "maxItems": 4,
                "description": "Required if kind='choice', exactly 4 options.",
            },
            "correct_index": {
                "type": "integer",
                "minimum": 0,
                "maximum": 3,
                "description": "Required if kind='choice', the 0-based index of the right option.",
            },
        },
        "required": ["milestone_id", "kind", "question"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.db is None:
            raise RuntimeError("pose_question requires a db session in ToolContext")

        milestone_id = UUID(str(args["milestone_id"]))
        kind = str(args["kind"])
        question = str(args["question"]).strip()
        if not question:
            raise ValueError("question must be non-empty")

        choices = args.get("choices")
        correct_index = args.get("correct_index")

        if kind == "choice":
            if choices is None or len(choices) != 4:
                raise ValueError("kind='choice' requires exactly 4 choices")
            if correct_index is None or not 0 <= int(correct_index) <= 3:
                raise ValueError("kind='choice' requires correct_index in [0, 3]")
            choices = [str(c) for c in choices]
            correct_index = int(correct_index)
        elif kind == "application":
            if choices is not None or correct_index is not None:
                raise ValueError(
                    "kind='application' must not include choices/correct_index"
                )
        else:
            raise ValueError(f"unknown kind {kind!r}")

        # Verify the milestone exists (FK enforces this on insert, but
        # raising a clean Python error is friendlier to the LLM).
        milestone = await MilestoneRepo(ctx.db).get_by_id(milestone_id)
        if milestone is None:
            raise ValueError(f"milestone {milestone_id} not found")

        attempt = await AttemptRepo(ctx.db).create(
            milestone_id=milestone_id,
            kind=kind,
            question=question,
            choices=choices,
            correct_index=correct_index,
        )

        return json.dumps(
            {
                "attempt_id": str(attempt.id),
                "kind": kind,
                "milestone_id": str(milestone_id),
            },
            ensure_ascii=False,
        )
