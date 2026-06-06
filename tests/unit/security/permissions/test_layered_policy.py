"""Tests for LayeredPolicy — three-gate composition (deny → rule → allow)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from berry.core.agent.approval import ApprovalDecision
from berry.core.tools.base import ToolContext
from berry.security.permissions.layered_policy import LayeredPolicy


def _ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp/berry_test"),
        cwd=Path("/tmp/berry_test"),
    )


def test_deny_list_match_returns_auto_deny() -> None:
    p = LayeredPolicy()
    v = p.decide("bash", {"command": "rm -rf /"}, _ctx())
    assert v.decision is ApprovalDecision.AUTO_DENY
    assert v.reason is not None
    assert "rm -rf /" in v.reason


def test_rule_match_returns_require_approval() -> None:
    p = LayeredPolicy()
    v = p.decide("bash", {"command": "rm foo.py"}, _ctx())
    assert v.decision is ApprovalDecision.REQUIRE_APPROVAL
    assert v.reason is not None
    assert "rm " in v.reason


def test_no_match_returns_auto_allow() -> None:
    p = LayeredPolicy()
    v = p.decide("bash", {"command": "ls -la"}, _ctx())
    assert v.decision is ApprovalDecision.AUTO_ALLOW
    assert v.reason is None


def test_non_bash_tool_skips_deny_gate() -> None:
    """write_file/etc. don't go through deny — only rules. Currently no
    rule applies to them → AUTO_ALLOW."""
    p = LayeredPolicy()
    v = p.decide("write_file", {"path": "/etc/passwd"}, _ctx())
    assert v.decision is ApprovalDecision.AUTO_ALLOW


def test_deny_takes_precedence_over_rule() -> None:
    """`rm -rf /` would also match the `'rm '` rule, but deny gate fires first."""
    p = LayeredPolicy()
    v = p.decide("bash", {"command": "rm -rf /"}, _ctx())
    assert v.decision is ApprovalDecision.AUTO_DENY


def test_bash_with_non_string_command_falls_through() -> None:
    """Robustness: weird arg types don't crash; just AUTO_ALLOW (rules also skip)."""
    p = LayeredPolicy()
    v = p.decide("bash", {"command": 123}, _ctx())
    assert v.decision is ApprovalDecision.AUTO_ALLOW
