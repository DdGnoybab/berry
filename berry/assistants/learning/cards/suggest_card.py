"""SUGGEST card — the heart of berry-L's user interaction.

After the LLM produces a SUGGEST (post_probe / post_teach / post_assess / ...),
runtime renders this card so the user can pick what to do next:

    ┌─ a3 quicklist · ASSESS 4 题完成 ──────────────────┐
    │ 均分: 5.0 / 10                                    │
    │ 漏的点: quicklist 节点为什么用 ziplist             │
    │                                                   │
    │ 我建议:⭐ 完整重讲 a3                              │
    │                                                   │
    │ [完整重讲 ⭐] [只补漏点] [换种方式讲] [深入讲]      │
    │ [再来一题] [换组题] [我懂了标 done] [跳过]          │
    └───────────────────────────────────────────────────┘

Design decisions (locked, 2026-06-06):
  - All options laid flat as buttons (Q1=a). No "more options ▾".
  - Sub-menu for `换种方式讲` / `深入讲` is rendered by **updating the same
    card** (Q2=b) — see ``build_suggest_card`` with ``sub_menu`` param.
  - Recommended options use ``primary`` style + ⭐ label prefix.

The card mirrors openclaw's approval-card pattern:
  - schema 2.0
  - blue header for SUGGEST (orange would feel "danger")
  - buttons carry a ``card_interaction`` envelope, validated on click
"""

from __future__ import annotations

import json
from typing import Any, Literal

from berry.channels.feishu.card_interaction import create_envelope
from berry.channels.feishu.card_ux_shared import build_button

LEARNING_PICK_OPTION_ACTION = "berry.learning.pick_option"
LEARNING_PICK_SUB_OPTION_ACTION = "berry.learning.pick_sub_option"

SuggestContext = Literal[
    "post_probe",
    "post_teach",
    "post_teach_lite",
    "post_teach_restyle",
    "post_teach_deeper",
    "post_assess",
]


_HEADER_BY_CONTEXT: dict[str, str] = {
    "post_probe": "摸底测完成",
    "post_teach": "讲解完成",
    "post_teach_lite": "补漏完成",
    "post_teach_restyle": "换种方式讲完",
    "post_teach_deeper": "深入讲解完成",
    "post_assess": "测试完成",
}


def _format_score_line(score: float | None, max_score: float = 10.0) -> str | None:
    if score is None:
        return None
    return f"**得分**:{score:.1f} / {max_score:.0f}"


def _format_weak_points(weak_points: list[str]) -> str | None:
    if not weak_points:
        return None
    if len(weak_points) == 1:
        return f"**漏的点**:{weak_points[0]}"
    bullets = "\n".join(f"  - {p}" for p in weak_points)
    return f"**漏的点**:\n{bullets}"


def _format_recommendation(options: list[dict[str, Any]]) -> str | None:
    """Pull the 1-2 recommended options into a leading 'I suggest' line."""
    recs = [o for o in options if o.get("recommended")]
    if not recs:
        return None
    if len(recs) == 1:
        return f"**我建议**:⭐ {recs[0]['label']}"
    labels = " 或 ".join(f"⭐ {o['label']}" for o in recs)
    return f"**我建议**:{labels}"


def _option_button(
    option: dict[str, Any],
    *,
    envelope_ctx: dict[str, Any],
    suggestion_id: str,
    is_sub: bool = False,
) -> dict[str, Any]:
    """Render a single option button.

    Recommended options get ``primary`` style and a ⭐ prefix.
    Strong recommendations (⭐⭐) ALSO get ``primary`` — Feishu only has 3
    button styles, so emphasis is via label prefix, not extra style.
    """
    label = option["label"]
    recommended = option.get("recommended", False)
    strong = option.get("strong_recommended", False)
    if strong:
        label = f"⭐⭐ {label}"
    elif recommended:
        label = f"⭐ {label}"
    style = "primary" if (recommended or strong) else "default"
    metadata = {
        "suggestion_id": suggestion_id,
        "key": option["key"],
    }
    action = LEARNING_PICK_SUB_OPTION_ACTION if is_sub else LEARNING_PICK_OPTION_ACTION
    return build_button(
        label=label,
        value=create_envelope(
            kind="button",
            action=action,
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
    """Feishu action containers can hold up to ~4 buttons per row before
    wrapping awkwardly on mobile. We pack into multiple ``action`` elements
    if we have more than ``per_row`` buttons.
    """
    rows: list[dict[str, Any]] = []
    for i in range(0, len(buttons), per_row):
        rows.append({"tag": "action", "actions": buttons[i : i + per_row]})
    return rows


def build_suggest_card(
    *,
    suggestion_id: str,
    atom_label: str,
    context: SuggestContext,
    score: float | None,
    weak_points: list[str],
    options: list[dict[str, Any]],
    extra_note: str | None = None,
    sub_menu: dict[str, Any] | None = None,
    user_open_id: str | None = None,
    chat_id: str | None = None,
    expires_at_ms: int | None = None,
) -> str:
    """Build the SUGGEST card content (Feishu interactive JSON string).

    Parameters
    ----------
    suggestion_id:
        Stable ID for this SUGGEST round (matches ``progress.json
        .current.last_suggestion``). Echoed in button envelopes so the runtime
        can detect stale clicks (user clicks a 2-step-old card).
    atom_label:
        Short label like ``"a3 quicklist"`` shown in the header.
    context:
        Which SUGGEST flavor — header label and visual hue derive from this.
    score / weak_points:
        Evaluation summary. ``score is None`` is allowed for post_teach
        (no test was taken).
    options:
        List of dicts: ``{key, label, recommended?, strong_recommended?,
        expands_to?}``. Order = display order.
    extra_note:
        Optional one-liner under the recommendation (e.g. the fail_count≥3
        warning, or the deeper_depth≥3 caveat).
    sub_menu:
        If present, render the SUB MENU instead of the main options. Shape::
            {
              "parent_choice": "teach_restyle",
              "options": [{"key": "vivid", "label": "..."}, ...]
            }
        The card title gets a "↘ 子菜单" suffix to signal we're one level deep.
    user_open_id / chat_id / expires_at_ms:
        Passed into button envelopes for click validation. ``expires_at_ms``
        defaults to None (no expiry) — SUGGEST options don't time out the
        way approvals do; user can take their time.

    Returns
    -------
    JSON string ready for ``msg_type=interactive`` send.
    """
    envelope_ctx = {
        "user_open_id": user_open_id,
        "chat_id": chat_id,
        "expires_at_ms": expires_at_ms,
    }

    is_sub = sub_menu is not None
    header_text = _HEADER_BY_CONTEXT.get(context, "建议")
    if is_sub:
        parent_label = sub_menu.get("parent_label", sub_menu.get("parent_choice", ""))
        title = f"berry-L · {atom_label} · ↘ {parent_label}"
    else:
        title = f"berry-L · {atom_label} · {header_text}"

    body_lines: list[str] = []

    if not is_sub:
        # main suggest body
        score_line = _format_score_line(score)
        if score_line:
            body_lines.append(score_line)
        weak_line = _format_weak_points(weak_points)
        if weak_line:
            body_lines.append(weak_line)
        if score_line or weak_line:
            body_lines.append("")  # blank
        rec_line = _format_recommendation(options)
        if rec_line:
            body_lines.append(rec_line)
        if extra_note:
            body_lines.append(extra_note)
        if rec_line or extra_note:
            body_lines.append("")
        body_lines.append("**或者你说了算 ↓**")
    else:
        body_lines.append(sub_menu.get("prompt", "你想我换什么方式 / 往哪深入?"))

    body_md = "\n".join(body_lines).strip()

    # button rendering
    render_options = sub_menu["options"] if is_sub else options
    buttons = [
        _option_button(opt, envelope_ctx=envelope_ctx, suggestion_id=suggestion_id, is_sub=is_sub)
        for opt in render_options
    ]
    action_rows = _chunk_buttons(buttons, per_row=4)

    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": body_md}]
    elements.extend(action_rows)

    # an inline hint that user can also just type freeform
    elements.append(
        {
            "tag": "markdown",
            "content": "_或直接打字:「让我看看刚才的题」「跳到 a5」「再深入一点」 等都可以_",
        }
    )

    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {"width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "body": {"elements": elements},
    }

    return json.dumps(card, ensure_ascii=False)


def build_suggest_card_resolved(
    *,
    atom_label: str,
    context: SuggestContext,
    chosen_label: str,
    was_recommended: bool,
) -> str:
    """Build the post-click 'resolved' state of a SUGGEST card.

    After the user clicks a button (or types a freeform choice), the runtime
    updates the card to remove buttons and show the chosen path — this prevents
    double-clicks and gives the user a stable record of what they picked.
    """
    badge = "⭐ " if was_recommended else ""
    body_md = (
        f"{_HEADER_BY_CONTEXT.get(context, '建议')} · 已选择\n\n"
        f"**你选了**:{badge}{chosen_label}"
    )
    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {"width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": f"berry-L · {atom_label}"},
            "template": "grey",
        },
        "body": {
            "elements": [{"tag": "markdown", "content": body_md}],
        },
    }
    return json.dumps(card, ensure_ascii=False)
