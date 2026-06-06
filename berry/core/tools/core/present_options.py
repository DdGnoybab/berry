"""PresentOptionsTool — 把选项以按钮形式推给前端。

LLM 调用此工具 → 工具 emit SuggestionEvent → 前端渲染按钮。
用户点击按钮 → 前端发送对应 key 作为文本消息。

工具 return 一个确认字符串给 LLM(不会被用户看到,因为 tool_result
在 SSE 里单独渲染)。
"""

from __future__ import annotations

from typing import Any, ClassVar

from berry.core.tools.base import ToolContext


class PresentOptionsTool:
    """Present clickable options to the user in the chat UI."""

    name: ClassVar[str] = "present_options"
    description: ClassVar[str] = (
        "Present a set of clickable options (buttons) to the user. "
        "Use this instead of typing numbered lists when you want the user "
        "to pick from choices. Each option has a key and a label. "
        "The user's choice arrives as their next message."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "suggestion_id": {
                "type": "string",
                "description": "Unique ID for this suggestion round (e.g. 'sg_mod1_atom2_post_probe')",
            },
            "context": {
                "type": "string",
                "description": "What triggered these options (e.g. 'post_probe', 'post_teach', 'post_assess', 'plan_review')",
            },
            "prompt": {
                "type": "string",
                "description": "A short prompt shown above the buttons (e.g. '你想怎么继续？')",
            },
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Stable key sent back as the user's message when clicked",
                        },
                        "label": {
                            "type": "string",
                            "description": "Human-readable label shown on the button",
                        },
                        "recommended": {
                            "type": "boolean",
                            "description": "Whether this option is recommended",
                            "default": False,
                        },
                    },
                    "required": ["key", "label"],
                },
                "minItems": 1,
                "maxItems": 8,
            },
        },
        "required": ["suggestion_id", "options"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        from berry.core.agent.suggestion_event import (
            SuggestionEvent,
            SuggestionOption,
            emit_suggestion,
        )

        options = [
            SuggestionOption(
                key=o["key"],
                label=o["label"],
                recommended=o.get("recommended", False),
            )
            for o in args.get("options", [])
        ]

        emit_suggestion(
            ctx.session_id,
            SuggestionEvent(
                suggestion_id=args.get("suggestion_id", ""),
                context=args.get("context", ""),
                prompt=args.get("prompt", ""),
                options=options,
            ),
        )

        n = len(options)
        return f"Presented {n} option(s) to the user. Wait for their choice."
