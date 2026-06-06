"""LayeredPolicy — composes deny-list + rule-matcher + fall-through.

Implements ``ApprovalPolicy``. Returns:
- AUTO_DENY  if a deny-list pattern matches (with reason)
- REQUIRE_APPROVAL  if a rule fires (with reason)
- AUTO_ALLOW  otherwise (no reason)
"""

from __future__ import annotations

from typing import Any

from berry.core.agent.approval import ApprovalDecision, PolicyVerdict
from berry.core.tools.base import ToolContext
from berry.security.permissions.deny_list import check_deny
from berry.security.permissions.rules import check_rules


class LayeredPolicy:
    """State-free; one instance per ``ConversationRuntime``."""

    # Deny-list only applies to bash (the only tool whose args are arbitrary
    # shell strings). Other tools rely on path_scope / their own validation.
    _DENY_CHECKED_TOOLS = frozenset({"bash"})

    def decide(
        self,
        tool_name: str,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> PolicyVerdict:
        if tool_name in self._DENY_CHECKED_TOOLS:
            cmd = args.get("command", "")
            if isinstance(cmd, str):
                matched = check_deny(cmd)
                if matched is not None:
                    return PolicyVerdict(
                        decision=ApprovalDecision.AUTO_DENY,
                        reason=f"matches deny pattern {matched!r}",
                    )

        rule_reason = check_rules(tool_name, args, ctx.cwd)
        if rule_reason is not None:
            return PolicyVerdict(
                decision=ApprovalDecision.REQUIRE_APPROVAL,
                reason=rule_reason,
            )

        return PolicyVerdict(decision=ApprovalDecision.AUTO_ALLOW)
