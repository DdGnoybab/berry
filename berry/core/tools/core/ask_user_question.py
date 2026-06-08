"""AskUserQuestionTool — present a multiple-choice question to the user.

Design philosophy is borrowed from Claude Code's built-in
``AskUserQuestion`` tool (see ADR-0010). Single, focused job: take a
question + a set of options, render them as buttons in whatever
channel the user is talking through, then return immediately so the
LLM can stop typing.

Architecture-wise:

  - LLM calls this tool with ``{question, options}``.
  - Tool emits a ``SuggestionEmitted`` event on the EventBus.
  - Channels (web SSE, Feishu cards, ...) subscribed to the bus
    render their own UI from that event.
  - Tool returns a short confirmation string so the LLM knows the
    options are now showing and stops generating text in the same turn.

The tool description is forceful on purpose. Plain experience:
without "MUST" + "never type numbered lists" + "STOP after",
the LLM regularly skips the tool call and just types the choices
inline as text — which doesn't render as buttons. See ADR-0010 for
the stability target (~95% with the three-layer reinforcement —
this description + the system prompt section + the nag reminder).
"""

from __future__ import annotations

import secrets
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext


def _generate_suggestion_id() -> str:
    """Short opaque ID — collision-resistant within a session deque
    of 8 entries; readable in logs."""
    return f"sg_{secrets.token_hex(4)}"


class AskUserQuestionTool:
    """Render a multiple-choice question as clickable buttons."""

    name: ClassVar[str] = "ask_user_question"
    description: ClassVar[str] = (
        "Ask the user to pick from a discrete set of options. "
        "Use this whenever you need a choice from the user — "
        "never type numbered lists like '1. foo  2. bar' as substitute. "
        "Options render as clickable buttons in the UI; the user's choice "
        "arrives as their next message. "
        "Buttons are rendered BELOW your assistant message in the chat — "
        "do NOT write '👆 上面' / 'tap above' / '看上面的按钮'. If you "
        "must point the user at the buttons, say '下方' / 'below' / use "
        "'👇'. Best of all: don't reference button location at all — the UI "
        "already makes them obvious. "
        "After calling this tool, STOP — do not write any more text in "
        "the same turn. Subsequent text would hide the buttons. "
        "Exception: simple binary yes/no questions can stay as plain text."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Short prompt shown above the buttons (e.g. 'Which approach?').",
            },
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": (
                                "Button text. Sent back as the user's next message verbatim "
                                "when clicked, so write it as a natural user reply."
                            ),
                        },
                        "description": {
                            "type": "string",
                            "description": (
                                "Optional one-line clarifier shown below the label "
                                "(useful for explaining a non-obvious option)."
                            ),
                        },
                        "recommended": {
                            "type": "boolean",
                            "description": "Mark this option as recommended (renders with a star).",
                            "default": False,
                        },
                    },
                    "required": ["label"],
                },
            },
        },
        "required": ["question", "options"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        # Deferred imports avoid a static ``core.tools -> core.agent``
        # dependency (import-linter rule 5). The agent layer is what
        # invokes this tool — it's already loaded by the time we get here.
        from berry.core.agent.event_bus import (
            SuggestionEmitted,
            SuggestionOption,
            get_event_bus,
        )
        from berry.core.agent.suggestion_registry import get_suggestion_registry

        question = args.get("question", "")
        raw_options = args.get("options") or []

        options = [
            SuggestionOption(
                label=o["label"],
                description=o.get("description"),
                recommended=bool(o.get("recommended", False)),
            )
            for o in raw_options
            if isinstance(o, dict) and "label" in o
        ]
        if not options:
            return "ask_user_question: no valid options provided; nothing rendered."

        suggestion_id = _generate_suggestion_id()

        # Record in the registry FIRST so a click that arrives faster than
        # the channel's render-and-show can still validate.
        get_suggestion_registry().record(
            session_id=ctx.session_id,
            suggestion_id=suggestion_id,
            options=[
                {
                    "label": o.label,
                    "description": o.description,
                    "recommended": o.recommended,
                }
                for o in options
            ],
        )

        get_event_bus().emit(
            ctx.session_id,
            SuggestionEmitted(
                suggestion_id=suggestion_id,
                prompt=question,
                options=options,
            ),
        )

        return (
            f"ask_user_question: presented {len(options)} option(s) to the user. "
            "Wait for their reply (their click arrives as the next user message)."
        )
