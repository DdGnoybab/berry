"""Approval decision model + policy/channel Protocols + a generic WhitelistPolicy.

claw-code lesson: enforce safety at tool-call boundary, not at prompt boundary.
ApprovalPolicy decides *whether* to ask;
ApprovalChannel decides *how* to ask the user (CLI Y/n / feishu card / ...).

Policies return ``PolicyVerdict`` rather than a bare ``ApprovalDecision`` so that
``runtime.py`` and channel implementations can surface a human-readable
``reason`` (e.g. "matches deny pattern 'rm -rf /'", "contains 'rm '") to both
the LLM (in the denial ToolResultBlock) and to the user (in the approval UI).

WhitelistPolicy is the only generic policy implementation in this module.
Domain-specific approval lists (e.g. learning's
{write_md, edit_md, propose_milestones, update_milestones}) are constructed
in assistants/<name>/tutor.py — NOT hard-coded here, per ADR-0003 rule 3
("core does not depend on assistants").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from berry.core.tools.base import ToolContext


class ApprovalDecision(StrEnum):
    """Outcome of an ApprovalPolicy decision.

    AUTO_DENY is reserved for policies that hard-block a tool without ever
    asking the user (e.g. the deny-list gate in ``LayeredPolicy``).
    WhitelistPolicy never returns it; consumers must still handle the value
    because other policies may.
    """

    AUTO_ALLOW = "auto_allow"
    REQUIRE_APPROVAL = "require_approval"
    AUTO_DENY = "auto_deny"


@dataclass(frozen=True)
class PolicyVerdict:
    """A policy's decision plus an optional human-readable reason.

    ``reason`` is filled for AUTO_DENY (so the LLM knows what was blocked)
    and for REQUIRE_APPROVAL (so the user / approval UI can explain why).
    For AUTO_ALLOW it is typically None.
    """

    decision: ApprovalDecision
    reason: str | None = None


@runtime_checkable
class ApprovalPolicy(Protocol):
    """Pure-function decision: should this tool call require user approval?"""

    def decide(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> PolicyVerdict: ...


@runtime_checkable
class ApprovalChannel(Protocol):
    """Asks the user; returns True=approved, False=denied.

    Implementations live in channels/{cli,feishu}/approval*.py.
    A denial is not an exception — runtime turns False into a
    ToolResultBlock(is_error=True, output="user denied") fed back to the LLM.

    ``reason`` is the optional explanation produced by the policy
    (e.g. "contains 'rm '"); channels should render it to the user when
    available so the approval prompt is self-explanatory.
    """

    async def ask(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
        reason: str | None = None,
    ) -> bool: ...


class WhitelistPolicy:
    """Requires approval for any tool whose name is in the whitelist;
    auto-allows everything else.

    Domain-specific approval sets are passed in by assistants:
        WhitelistPolicy({"write_md", "edit_md", ...})
    """

    def __init__(self, approval_required: set[str]) -> None:
        self._approval_required = frozenset(approval_required)

    def decide(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> PolicyVerdict:
        if tool_name in self._approval_required:
            return PolicyVerdict(
                decision=ApprovalDecision.REQUIRE_APPROVAL,
                reason=f"{tool_name} requires approval",
            )
        return PolicyVerdict(decision=ApprovalDecision.AUTO_ALLOW)
