"""Pure logic for processing a SUGGEST card click.

When a user clicks a button on a SUGGEST card, ``card_action.py`` decodes
the envelope (validates user / chat / expiry) and reaches here for the
business decision: what does this click MEAN, and how does it become a
follow-up turn for the LLM?

We deliberately separate this from ``card_action.py`` (which is approval-
specific) and from any I/O — this module returns a ``ClickDecision`` that
describes WHAT to do; the channel layer wires up the actual side effects
(send a "续上" turn to the runtime, update the resolved card, etc.).

Tested in isolation against a fixture progress.json so we don't need lark.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from berry.assistants.learning.cards.suggest_card import (
    LEARNING_PICK_OPTION_ACTION,
    LEARNING_PICK_SUB_OPTION_ACTION,
)
from berry.observability.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ClickDecision:
    """Result of processing a SUGGEST card click.

    The channel uses this to:
    1. Render a "resolved" version of the SUGGEST card (with chosen_label)
    2. Inject ``synthesized_user_message`` as the next turn's user input
       — i.e. simulate the user typing the option label, so the LLM sees a
       normal turn and follows §3 type A in SKILL.md (AWAITING_USER → choice).
    """

    kind: Literal["pick_option", "pick_sub_option", "stale", "unknown_key", "missing_progress"]
    chosen_key: str | None = None
    chosen_label: str | None = None
    was_recommended: bool = False
    """Whether the chosen option was a (single or strong) recommendation."""
    expands_to: str | None = None
    """If non-None, the option is one that expands to a sub-menu (e.g.
    ``restyle_modes`` or ``deeper_directions``). The channel should NOT
    inject a synthesized user turn yet — it should just render the sub-menu
    in the same card. The actual follow-up turn happens after the user
    picks a sub-option.
    """
    synthesized_user_message: str | None = None
    """The text the channel should feed into the runtime as the next turn's
    user input. ``None`` when ``expands_to`` is set, or when ``kind`` is an
    error variant.
    """
    suggestion_id: str | None = None
    """Echoed for logging / dedup."""


def _read_progress(workspace_path: Path) -> dict[str, Any] | None:
    p = workspace_path / ".berry" / "progress.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "click_progress_read_failed",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None


def process_click(
    *,
    action_name: str,
    metadata: dict[str, Any],
    workspace_path: Path,
) -> ClickDecision:
    """Translate a card click into a follow-up action.

    Parameters
    ----------
    action_name:
        ``LEARNING_PICK_OPTION_ACTION`` or ``LEARNING_PICK_SUB_OPTION_ACTION``.
    metadata:
        ``envelope.m`` from the click — should have ``suggestion_id`` and
        ``key`` (set by ``suggest_card.build_suggest_card``).
    workspace_path:
        Where progress.json lives — we read it to validate ``suggestion_id``
        and look up the option's label / recommended flag / expands_to.

    Returns
    -------
    A ``ClickDecision`` describing what to do. ``kind`` indicates outcome.
    """
    suggestion_id = metadata.get("suggestion_id")
    chosen_key = metadata.get("key")

    if action_name not in (
        LEARNING_PICK_OPTION_ACTION,
        LEARNING_PICK_SUB_OPTION_ACTION,
    ):
        return ClickDecision(kind="unknown_key", suggestion_id=suggestion_id)

    progress = _read_progress(workspace_path)
    if progress is None:
        return ClickDecision(kind="missing_progress", suggestion_id=suggestion_id)

    current = progress.get("current") or {}
    last = current.get("last_suggestion") or {}

    # Stale-click guard: clicked card's suggestion_id no longer matches
    # current state (LLM advanced past this SUGGEST). Treat as stale.
    if suggestion_id and last.get("suggestion_id") and last["suggestion_id"] != suggestion_id:
        return ClickDecision(kind="stale", suggestion_id=suggestion_id)

    if action_name == LEARNING_PICK_OPTION_ACTION:
        options = last.get("options") or []
        opt = next((o for o in options if o.get("key") == chosen_key), None)
        if opt is None:
            return ClickDecision(kind="unknown_key", suggestion_id=suggestion_id)
        recommended = bool(opt.get("recommended") or opt.get("strong_recommended"))
        expands_to = opt.get("expands_to")
        if expands_to:
            return ClickDecision(
                kind="pick_option",
                chosen_key=chosen_key,
                chosen_label=opt.get("label"),
                was_recommended=recommended,
                expands_to=expands_to,
                synthesized_user_message=None,
                suggestion_id=suggestion_id,
            )
        return ClickDecision(
            kind="pick_option",
            chosen_key=chosen_key,
            chosen_label=opt.get("label"),
            was_recommended=recommended,
            expands_to=None,
            synthesized_user_message=opt.get("label"),
            suggestion_id=suggestion_id,
        )

    # LEARNING_PICK_SUB_OPTION_ACTION
    sub = last.get("sub_menu") or {}
    sub_options = sub.get("options") or []
    opt = next((o for o in sub_options if o.get("key") == chosen_key), None)
    if opt is None:
        return ClickDecision(kind="unknown_key", suggestion_id=suggestion_id)
    parent_label = sub.get("parent_label") or sub.get("parent_choice") or ""
    label = opt.get("label", chosen_key)
    # The follow-up "user message" combines parent context + sub choice so
    # the LLM unambiguously sees what the user picked across both menus.
    synthesized = f"{parent_label} → {label}" if parent_label else label
    return ClickDecision(
        kind="pick_sub_option",
        chosen_key=chosen_key,
        chosen_label=label,
        was_recommended=False,
        expands_to=None,
        synthesized_user_message=synthesized,
        suggestion_id=suggestion_id,
    )
