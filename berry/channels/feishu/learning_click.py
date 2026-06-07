"""Feishu SUGGEST card click handler.

When the user clicks a button on a SUGGEST card, ``card_action.py``
(after envelope decoding + sender validation) calls into this module
to translate the click into a follow-up turn.

After ADR-0010, all suggestion state lives in
``core.agent.suggestion_registry`` (not ``progress.json``). The click
flow is:

    click → registry.lookup(suggestion_id) → option found?
        ├─ no  → stale / unknown_key
        └─ yes → synthesise user message = option.label, run a turn.

Tested against an in-memory ``SuggestionRegistry`` so we don't need
lark or workspace files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from berry.core.agent.suggestion_registry import (
    SuggestionRegistry,
    get_suggestion_registry,
)
from berry.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ClickDecision:
    """Result of processing a SUGGEST card click.

    Channel uses this to:
      1. Render a "resolved" version of the card (with chosen_label)
      2. Inject ``synthesized_user_message`` as the next turn's user input
    """

    kind: Literal["pick_option", "stale", "unknown_label"]
    chosen_label: str | None = None
    was_recommended: bool = False
    synthesized_user_message: str | None = None
    suggestion_id: str | None = None


def process_click(
    *,
    session_id: str,
    metadata: dict[str, Any],
    registry: SuggestionRegistry | None = None,
) -> ClickDecision:
    """Translate a card click into a follow-up action.

    Parameters
    ----------
    session_id:
        The session this card belongs to.
    metadata:
        ``envelope.m`` from the click — set by
        ``cards/suggest_card.build_suggest_card`` to ``{suggestion_id, label}``.
    registry:
        Override for tests; defaults to the process-wide registry.
    """
    reg = registry if registry is not None else get_suggestion_registry()
    suggestion_id = metadata.get("suggestion_id")
    chosen_label = metadata.get("label")

    if not suggestion_id or not chosen_label:
        return ClickDecision(kind="unknown_label", suggestion_id=suggestion_id)

    options = reg.lookup(session_id=session_id, suggestion_id=suggestion_id)
    if options is None:
        return ClickDecision(kind="stale", suggestion_id=suggestion_id)

    matched = next((o for o in options if o.get("label") == chosen_label), None)
    if matched is None:
        return ClickDecision(
            kind="unknown_label",
            chosen_label=chosen_label,
            suggestion_id=suggestion_id,
        )

    return ClickDecision(
        kind="pick_option",
        chosen_label=chosen_label,
        was_recommended=bool(matched.get("recommended")),
        synthesized_user_message=chosen_label,
        suggestion_id=suggestion_id,
    )
