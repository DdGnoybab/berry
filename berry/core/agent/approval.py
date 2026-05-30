"""Approval decision model + policy/channel Protocols + a generic WhitelistPolicy.

claw-code lesson: enforce safety at tool-call boundary, not at prompt boundary.
ApprovalPolicy decides *whether* to ask;
ApprovalChannel decides *how* to ask the user (CLI Y/n / feishu card / ...).

WhitelistPolicy is the only generic policy implementation in this module.
Domain-specific approval lists (e.g. learning's
{write_md, edit_md, propose_milestones, update_milestones}) are constructed
in assistants/<name>/tutor.py — NOT hard-coded here, per ADR-0003 rule 3
("core does not depend on assistants").
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from berry.core.tools.base import ToolContext


class ApprovalDecision(StrEnum):
    """Outcome of an ApprovalPolicy decision.

    AUTO_DENY is reserved for policies that hard-block a tool without ever
    asking the user (e.g. a future rate-limit policy, or a CI runner that
    forbids `write_md` regardless of who's asking). WhitelistPolicy never
    returns it; consumers must still handle the value because other policies
    may.
    """

    AUTO_ALLOW = "auto_allow"
    REQUIRE_APPROVAL = "require_approval"
    AUTO_DENY = "auto_deny"


@runtime_checkable
class ApprovalPolicy(Protocol):
    """Pure-function decision: should this tool call require user approval?"""

    def decide(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ApprovalDecision: ...


@runtime_checkable
class ApprovalChannel(Protocol):
    """Asks the user; returns True=approved, False=denied.

    Implementations live in channels/{cli,feishu}/approval.py.
    A denial is not an exception — runtime turns False into a
    ToolResultBlock(is_error=True, output="user denied") fed back to the LLM.
    """

    async def ask(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
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
    ) -> ApprovalDecision:
        if tool_name in self._approval_required:
            return ApprovalDecision.REQUIRE_APPROVAL
        return ApprovalDecision.AUTO_ALLOW
