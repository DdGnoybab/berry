"""Feishu card schemas.

Cards are channel-specific rendering. They live in the feishu channel,
not in skills/<name>/, because:
  - Different channels render the same logical event differently
    (web shows buttons inline; feishu shows a card; CLI prints).
  - import-linter rule 5 forbids channels from importing skills.

Suggestion-button rendering takes ``BerryEvent.SuggestionEmitted`` from
core/agent/event_bus.py — channel-agnostic data shape — and produces
a feishu card. The same event drives the web channel's SSE output.
"""

from berry.channels.feishu.cards.progress_overview_card import (
    build_progress_overview_card,
)
from berry.channels.feishu.cards.suggest_card import (
    LEARNING_PICK_OPTION_ACTION,
    build_suggest_card,
    build_suggest_card_resolved,
)

__all__ = [
    "LEARNING_PICK_OPTION_ACTION",
    "build_progress_overview_card",
    "build_suggest_card",
    "build_suggest_card_resolved",
]
