"""Trailing-question nag — detect when an assistant turn ends in a
question (asking the user to pick something) but never called
``ask_user_question``.

The class of bug this catches:
  - ASSESS scoring done, LLM transitions to SUGGEST.
  - LLM types a summary + closing line like "下一个 atom?" / "继续吗?".
  - LLM forgets to call ask_user_question — turn ends with stop=end_turn.
  - User sees no buttons, has to type the choice manually.

This is distinct from phantom_buttons_nag (which catches references to
buttons that don't exist) and numbered_list_nag (which catches numbered
options as text). Here the LLM produced a plain-text question with NO
list structure and NO button reference — the most common form of
SUGGEST drift on weaker tool-calling models.

Detection rules (any one matches):
  - Last non-empty line ends in ``?`` / ``？`` AND looks like a choice
    prompt (contains 还是 / 要不要 / 想 / 继续 / 下一 / next / continue / pick).
  - Last non-empty line is ONE of the canonical SUGGEST closers
    (e.g. "下一个 atom?" / "你想怎么继续?" / "what's next?").

We're conservative: a question mark alone isn't enough — quizzes ("Q1.
什么是 SDS?") legitimately end in ?. The choice-vocabulary gate keeps
false positives low.
"""  # noqa: RUF002

from __future__ import annotations

import re
from dataclasses import dataclass

# Tokens that strongly suggest "I want you to pick something". Mixed
# zh/en because the same skill talks to either. Keep tight — broadening
# this is what makes the detector noisy.
_CHOICE_TOKENS = re.compile(
    r"(还是|要不要|想怎么|想不想|继续吗|下一个|下一步|"
    r"\bnext\b|\bcontinue\b|\bpick\b|\bchoose\b|\bwhich\b|\bwhat'?s next\b)",
    re.IGNORECASE,
)

# Question-mark suffix (allow trailing whitespace / quotes / brackets).
_QUESTION_SUFFIX = re.compile(r"[?？][\s\"'’”』」）)\]]*$")  # noqa: RUF001


@dataclass
class TrailingQuestionNag:
    triggered: bool
    sample: str = ""


def detect(text: str, *, tools_called: set[str]) -> TrailingQuestionNag:
    """Inspect this turn's assistant text and tool calls.

    Returns ``TrailingQuestionNag(triggered=True, sample=...)`` when
    the last non-empty line is a choice prompt and the LLM didn't call
    ``ask_user_question`` this turn.
    """
    if "ask_user_question" in tools_called:
        return TrailingQuestionNag(triggered=False)

    # Last non-empty line — strip blockquote / list markers that often
    # wrap the closing question ("> 下一个 atom?", "- 继续吗?").
    last_line = ""
    for raw in reversed(text.splitlines()):
        stripped = raw.strip()
        if not stripped:
            continue
        last_line = re.sub(r"^[>*\-\d.)\s]+", "", stripped)
        break

    if not last_line:
        return TrailingQuestionNag(triggered=False)

    if not _QUESTION_SUFFIX.search(last_line):
        return TrailingQuestionNag(triggered=False)

    if not _CHOICE_TOKENS.search(last_line):
        return TrailingQuestionNag(triggered=False)

    return TrailingQuestionNag(triggered=True, sample=last_line[:80])


REMINDER_TEMPLATE = (
    "<system-reminder>\n"
    'Your previous response ended with a question to the user (e.g. "{sample}") '
    "but you did NOT call ask_user_question. The user sees no buttons and has "
    "to retype the choice manually — that's the exact failure mode "
    "ask_user_question exists to prevent.\n"
    "If the user needs to pick from a discrete set of options, call "
    "ask_user_question NOW with concrete options, then STOP. "
    "If the question was rhetorical / informational (no choice needed), "
    "just continue normally — but in that case don't end on a question "
    "mark next time.\n"
    "</system-reminder>"
)


def render_reminder(nag: TrailingQuestionNag) -> str:
    return REMINDER_TEMPLATE.format(sample=nag.sample or "下一个 atom?")
