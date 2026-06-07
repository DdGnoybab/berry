"""Phantom-buttons nag — detect when the LLM refers to buttons or options
from a prior turn while NOT calling ``ask_user_question`` in this turn.

The class of bug this catches:
  - User opens chat fresh; history says "ask_user_question was called 2 turns ago".
  - LLM types "click the buttons above" / "上面的按钮" / "点击刚才那 3 个选项".
  - User sees no buttons (they vanished after that previous turn).
  - LLM has fabricated UI state.

Pattern detection is intentionally fuzzy — false positives are cheap (one
extra reminder), false negatives leave gaslighting in place. We err
toward more matches.

Bilingual matching (Chinese + English) since the same user is likely to
get either prompt depending on locale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Each pattern is fragment-level. We OR them in detect().
# Avoid lookbehinds; keep simple for portability.
_PATTERNS = [
    # Chinese: 上面/上方/下面/下方 ... 按钮/选项 — directional pointers
    re.compile(r"(上面|上方|下面|下方|底下).{0,12}?(按钮|选项|的|那|来选)"),
    # Chinese: 点击/点 + 上面/下面/那个/刚才/这里
    re.compile(r"点(?:击|一下)?[^\s,。.!?]{0,12}?(上面|下面|那(?:个|些|3|三)|刚才|这里)"),
    # Chinese: 刚才 ... 问/选项/问题/的
    re.compile(r"刚才.{0,8}?(问|选项|问题|的|那)"),
    # Chinese: "那 N 个 选项/按钮"
    re.compile(r"那\s*[0-9一二三四五六七八九十]+\s*个\s*(选项|按钮)"),
    # Chinese: 还在那 / 还在
    re.compile(r"(问题|选项).{0,4}?还在"),
    # English: click/pick/choose ... above / below / earlier — directional pointers
    re.compile(
        r"\b(click|pick|choose|select|tap)\b[^.]{0,30}\b(above|below|earlier|previous|the buttons?)\b",
        re.IGNORECASE,
    ),
    # English: "the N options/buttons (I gave you|above|from before)"
    re.compile(r"\bthe\s+\d+\s+(options|buttons|choices)\b", re.IGNORECASE),
    # English: "options I (gave|presented|asked) ..."
    re.compile(r"\boptions\s+I\s+(gave|presented|asked|showed)\b", re.IGNORECASE),
    # English: bare "the buttons above/below"
    re.compile(r"\bthe\s+buttons?\s+(above|below)\b", re.IGNORECASE),
]


@dataclass
class PhantomButtonsNag:
    triggered: bool
    sample: str = ""


def detect(text: str, *, tools_called: set[str]) -> PhantomButtonsNag:
    """Inspect this turn's assistant text and the tool calls.

    If text references past buttons but ask_user_question wasn't called
    this turn, returns triggered=True with a short sample.
    """
    if "ask_user_question" in tools_called:
        return PhantomButtonsNag(triggered=False)

    for pat in _PATTERNS:
        m = pat.search(text)
        if m:
            # Sample: a small window around the match so the reminder
            # quotes back what the LLM actually said.
            start = max(0, m.start() - 5)
            end = min(len(text), m.end() + 15)
            sample = text[start:end].replace("\n", " ")[:80]
            return PhantomButtonsNag(triggered=True, sample=sample)

    return PhantomButtonsNag(triggered=False)


REMINDER_TEMPLATE = (
    "<system-reminder>\n"
    "Your previous response pointed the user at buttons "
    '(e.g. "{sample}…") but you did NOT call ask_user_question in that turn. '
    "Two things wrong with this:\n"
    "  1. The buttons you're referring to are gone — buttons rendered "
    "     by ask_user_question only exist during the turn that called "
    "     the tool. The user sees NO buttons.\n"
    '  2. Even if you had just called the tool, telling the user to '
    '     "click above/below/the buttons" is wrong — different channels '
    '     render in different positions, and "click" is redundant '
    "     anyway. Call the tool, then STOP — the UI handles the rest.\n"
    "If you need a user choice, call ask_user_question NOW with the "
    "actual options, then write nothing more.\n"
    "</system-reminder>"
)


def render_reminder(nag: PhantomButtonsNag) -> str:
    return REMINDER_TEMPLATE.format(sample=nag.sample or "上面的按钮")
