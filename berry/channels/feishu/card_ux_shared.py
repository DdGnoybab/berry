"""Shared Feishu card-element builders.

Mirrors openclaw ``extensions/feishu/src/card-ux-shared.ts``. Currently only
``build_button`` — extend as more card UIs land.
"""

from __future__ import annotations

from typing import Any, Literal

ButtonStyle = Literal["default", "primary", "danger"]


def build_button(
    *,
    label: str,
    value: dict[str, Any],
    style: ButtonStyle = "default",
) -> dict[str, Any]:
    """Build a Feishu interactive card button element.

    ``value`` is the envelope from ``card_interaction.create_envelope``;
    Feishu serializes it back to the ``card.action.trigger`` event's
    ``event.action.value`` field on click.
    """
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": style,
        "value": value,
    }
