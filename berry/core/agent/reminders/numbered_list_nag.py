"""Numbered-list nag — detect when the LLM types options as plain text
instead of calling ``ask_user_question``.

Pattern: any assistant text containing two or more lines that start
with ``"1. "`` / ``"2. "`` / etc. (numbered list), AND no
``ask_user_question`` tool was called in the same turn.

When detected, the runtime injects a reminder before the next LLM
call so the model corrects course.

Why "≥2 lines"? A single ``"1. ..."`` line is just enumerated prose
("Step 1. Read the file."). Two or more numbered lines, sequentially,
is an option list — and that's what we forbid. We don't try to detect
``"a) foo  b) bar"`` style; the system prompt and tool description
both target numbered lists explicitly, and the false-positive cost of
broader patterns is high.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Whole line that starts with a single digit + . or ) + whitespace + body.
# Sample-friendly: capture the body so the reminder shows what we saw.
NUMBERED_LIST_PATTERN = re.compile(r"^[ \t]*([1-9][.)][ \t]+\S[^\n]*)", re.MULTILINE)


@dataclass
class NumberedListNag:
    """Result of detection. ``triggered=True`` means a nag should fire
    on the NEXT turn.
    """

    triggered: bool
    sample: str = ""


def detect(text: str, *, tools_called: set[str]) -> NumberedListNag:
    """Inspect this turn's assistant text and the tool calls made.

    Returns a NumberedListNag; check ``.triggered``.
    """
    if "ask_user_question" in tools_called:
        return NumberedListNag(triggered=False)

    matches = NUMBERED_LIST_PATTERN.findall(text)
    if len(matches) >= 2:
        return NumberedListNag(triggered=True, sample=matches[0].strip()[:80])
    return NumberedListNag(triggered=False)


REMINDER_TEMPLATE = (
    "<system-reminder>\n"
    "Your previous response contained a numbered list of options "
    '(starting like "{sample}…") without calling ask_user_question. '
    "Numbered lists in text don't render as buttons — the user has to "
    "manually retype the choice. If you meant to ask the user to pick, "
    "call ask_user_question now with those options as buttons. "
    "If the list was just informational (steps, facts), ignore this.\n"
    "</system-reminder>"
)


def render_reminder(nag: NumberedListNag) -> str:
    """Format the reminder text the runtime should inject."""
    return REMINDER_TEMPLATE.format(sample=nag.sample or "1. ...")
