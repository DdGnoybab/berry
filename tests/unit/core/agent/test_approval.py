"""Tests for ApprovalDecision + WhitelistPolicy.

ApprovalChannel Protocol is tested at integration level when CLI / feishu
implementations exist (Round 2/5). Here we cover only the policy.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from berry.core.agent.approval import (
    ApprovalDecision,
    WhitelistPolicy,
)
from berry.core.tools.base import ToolContext


def _ctx() -> ToolContext:
    return ToolContext(
        session_id=uuid4(),
        user_id=uuid4(),
        db=None,
        data_root=Path("/tmp/berry_test"),
    )


def test_whitelist_policy_requires_approval_for_listed_tool() -> None:
    policy = WhitelistPolicy({"write_md", "edit_md"})
    decision = policy.decide("write_md", {"filename": "x.md"}, _ctx())
    assert decision is ApprovalDecision.REQUIRE_APPROVAL


def test_whitelist_policy_auto_allows_unlisted_tool() -> None:
    policy = WhitelistPolicy({"write_md"})
    decision = policy.decide("read_md", {"id": "abc"}, _ctx())
    assert decision is ApprovalDecision.AUTO_ALLOW


def test_whitelist_policy_empty_set_allows_everything() -> None:
    policy = WhitelistPolicy(set())
    decision = policy.decide("anything", {}, _ctx())
    assert decision is ApprovalDecision.AUTO_ALLOW


def test_whitelist_policy_decisions_are_string_enum() -> None:
    """ApprovalDecision values must be JSON-serializable as plain strings (StrEnum)."""
    assert str(ApprovalDecision.REQUIRE_APPROVAL) == "require_approval"
    assert str(ApprovalDecision.AUTO_ALLOW) == "auto_allow"
    assert str(ApprovalDecision.AUTO_DENY) == "auto_deny"
