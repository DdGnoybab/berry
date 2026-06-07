"""SUGGEST card — renders ``SuggestionEmitted`` events as a Feishu interactive card.

After the LLM calls the ``ask_user_question`` tool, the event bus carries
a ``SuggestionEmitted`` whose only fields are ``prompt`` and ``options``.
This module turns that into a Feishu card with one button per option.

Visual::

    ┌─ Berry · 你想怎么继续? ─────────────────────────────┐
    │                                                       │
    │ [⭐ 完整重讲] [换种方式讲] [深入讲]                    │
    │ [再来一题] [换组题] [我懂了标 done] [跳过]              │
    │                                                       │
    │ _或直接打字告诉我_                                      │
    └───────────────────────────────────────────────────────┘

Single action namespace: ``berry.suggest.pick``. There used to be a
separate ``berry.learning.pick_sub_option`` for two-level menus
(restyle_modes / deeper_directions). After ADR-0010 the LLM emits the
sub-menu as a fresh ``ask_user_question`` round, so a single click
handler suffices.

The card mirrors openclaw's approval-card pattern:
  - schema 2.0
  - blue header
  - buttons carry a ``card_interaction`` envelope, validated on click
"""

from __future__ import annotations

import json
from typing import Any

from berry.channels.feishu.card_interaction import create_envelope
from berry.channels.feishu.card_ux_shared import build_button

LEARNING_PICK_OPTION_ACTION = "berry.suggest.pick"


def _option_button(
    option: dict[str, Any],
    *,
    envelope_ctx: dict[str, Any],
    suggestion_id: str,
) -> dict[str, Any]:
    """Render a single option button.

    Recommended options get ``primary`` style and a ⭐ prefix.
    """
    label = option["label"]
    recommended = option.get("recommended", False)
    if recommended:
        label = f"⭐ {label}"
    style = "primary" if recommended else "default"
    metadata = {
        "suggestion_id": suggestion_id,
        # ``label`` is the canonical click payload — see ADR-0010 for why
        # we dropped the separate ``key`` field. Echoing the original
        # (unprefixed) label so the click handler reconstructs the exact
        # message the user "typed".
        "label": option["label"],
    }
    return build_button(
        label=label,
        value=create_envelope(
            kind="button",
            action=LEARNING_PICK_OPTION_ACTION,
            metadata=metadata,
            expected_user_open_id=envelope_ctx.get("user_open_id"),
            expected_chat_id=envelope_ctx.get("chat_id"),
            expires_at_ms=envelope_ctx.get("expires_at_ms"),
        ),
        style=style,
    )


def _chunk_buttons(
    buttons: list[dict[str, Any]], per_row: int = 4
) -> list[dict[str, Any]]:
    """Pack into multiple ``action`` elements when we have more than
    ``per_row`` buttons (Feishu wraps awkwardly past ~4).
    """
    rows: list[dict[str, Any]] = []
    for i in range(0, len(buttons), per_row):
        rows.append({"tag": "action", "actions": buttons[i : i + per_row]})
    return rows


def build_suggest_card(
    *,
    suggestion_id: str,
    prompt: str,
    options: list[dict[str, Any]],
    user_open_id: str | None = None,
    chat_id: str | None = None,
    expires_at_ms: int | None = None,
) -> str:
    """Build the SUGGEST card content (Feishu interactive JSON string).

    Parameters
    ----------
    suggestion_id:
        Stable ID for this round; echoed in button envelopes so
        ``SuggestionRegistry`` can detect stale clicks.
    prompt:
        Plain text shown above the buttons (e.g. "你想怎么继续?").
    options:
        List of dicts: ``{label, description?, recommended?}``.
        Order = display order. ``label`` IS the click-back payload (no
        separate ``key``).
    user_open_id / chat_id / expires_at_ms:
        Passed into button envelopes for click validation.

    Returns
    -------
    JSON string ready for ``msg_type=interactive`` send.
    """
    envelope_ctx = {
        "user_open_id": user_open_id,
        "chat_id": chat_id,
        "expires_at_ms": expires_at_ms,
    }

    body_lines: list[str] = []
    if prompt:
        body_lines.append(prompt)
    # Render option descriptions inline so users see the long-form
    # explanation without clicking.
    desc_lines = [
        f"- **{o['label']}** — {o['description']}"
        for o in options
        if o.get("description")
    ]
    if desc_lines:
        body_lines.append("")
        body_lines.extend(desc_lines)

    body_md = "\n".join(body_lines).strip() or "请选择:"

    buttons = [
        _option_button(opt, envelope_ctx=envelope_ctx, suggestion_id=suggestion_id)
        for opt in options
    ]
    action_rows = _chunk_buttons(buttons, per_row=4)

    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": body_md}]
    elements.extend(action_rows)
    elements.append(
        {
            "tag": "markdown",
            "content": "_或直接打字告诉我_",
        }
    )

    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {"width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": "Berry · 请选择"},
            "template": "blue",
        },
        "body": {"elements": elements},
    }

    return json.dumps(card, ensure_ascii=False)


def build_suggest_card_resolved(
    *,
    chosen_label: str,
    was_recommended: bool,
) -> str:
    """Build the post-click 'resolved' state of a SUGGEST card.

    After the user clicks (or types a freeform choice), the runtime
    updates the card to remove buttons and show the chosen path —
    prevents double-clicks and gives a stable record.
    """
    badge = "⭐ " if was_recommended else ""
    body_md = f"已选择 · {badge}{chosen_label}"
    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {"width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": "Berry"},
            "template": "grey",
        },
        "body": {
            "elements": [{"tag": "markdown", "content": body_md}],
        },
    }
    return json.dumps(card, ensure_ascii=False)
