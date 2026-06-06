"""PreToolUse hook — user-defined interception before tool execution.

Runs *before* ``ApprovalPolicy``.  Three outcomes:

- **ALLOW**  — skip policy + approval channel, execute the tool immediately.
- **DENY**   — block execution; return an error ToolResult to the LLM.
- **DEFER**  — hand off to the next hook, then to the existing policy chain.

Hooks are plain Python callables implementing ``PreToolUseHook``.
They are registered on ``HookRunner`` and injected into ``ConversationRuntime``.

Shell-script hooks (claw-code style) are deferred to V1 — see
``docs/claw-code-hooks-explained.md`` for the reference design.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

import structlog

from berry.core.tools.base import ToolContext

logger = structlog.get_logger(__name__)


# ── Verdict types ────────────────────────────────────────────────────────


class HookVerdictAction(StrEnum):
    """What a PreToolUse hook wants to happen."""

    ALLOW = "allow"
    DENY = "deny"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class HookVerdict:
    """Return value from ``PreToolUseHook.run``.

    ``reason`` is surfaced to the LLM (for DENY) or logged (for ALLOW).
    """

    action: HookVerdictAction
    reason: str | None = None


# Convenience constructors — keeps call-sites readable.
ALLOW = HookVerdictAction.ALLOW
DENY = HookVerdictAction.DENY
DEFER = HookVerdictAction.DEFER


def allow(reason: str | None = None) -> HookVerdict:
    return HookVerdict(action=ALLOW, reason=reason)


def deny(reason: str) -> HookVerdict:
    return HookVerdict(action=DENY, reason=reason)


def defer() -> HookVerdict:
    return HookVerdict(action=DEFER)


# ── Protocol ─────────────────────────────────────────────────────────────


@runtime_checkable
class PreToolUseHook(Protocol):
    """A single hook that runs before a tool is executed.

    Implementations must be async and return a ``HookVerdict``.
    """

    async def run(
        self,
        tool_name: str,
        args: dict[str, object],
        ctx: ToolContext,
    ) -> HookVerdict: ...


# ── Runner ───────────────────────────────────────────────────────────────


class HookRunner:
    """Executes an ordered list of ``PreToolUseHook`` instances.

    First non-DEFER verdict wins.  If all hooks DEFER (or the list is
    empty), the runner returns DEFER.

    If a hook raises, the runner logs the error and returns DENY —
    a safe default that prevents silent bypass of user-defined rules.
    """

    def __init__(self, hooks: list[PreToolUseHook] | None = None) -> None:
        self._hooks: tuple[PreToolUseHook, ...] = tuple(hooks or ())

    @property
    def hook_count(self) -> int:
        return len(self._hooks)

    async def run(
        self,
        tool_name: str,
        args: dict[str, object],
        ctx: ToolContext,
    ) -> HookVerdict:
        for hook in self._hooks:
            try:
                verdict = await hook.run(tool_name, args, ctx)
            except Exception:
                logger.exception(
                    "hook_raised",
                    hook=type(hook).__name__,
                    tool=tool_name,
                )
                return deny(
                    f"hook {type(hook).__name__} raised {type(Exception).__name__}; "
                    "blocking as safety default"
                )

            if verdict.action is not DEFER:
                logger.debug(
                    "hook_decided",
                    hook=type(hook).__name__,
                    action=verdict.action.value,
                    tool=tool_name,
                    reason=verdict.reason,
                )
                return verdict

        return defer()
