"""Permission gates: deny list (hard block) + rule matcher (ask user).

Pure-data + pure-function module (``deny_list``, ``rules``) plus
``LayeredPolicy`` which composes them into a ``berry.core.agent.approval.ApprovalPolicy``
implementation.
"""

from berry.security.permissions.deny_list import DENY_PATTERNS, check_deny
from berry.security.permissions.layered_policy import LayeredPolicy
from berry.security.permissions.rules import RULES, SUSPICIOUS_BASH_TOKENS, Rule, check_rules

__all__ = [
    "DENY_PATTERNS",
    "RULES",
    "SUSPICIOUS_BASH_TOKENS",
    "LayeredPolicy",
    "Rule",
    "check_deny",
    "check_rules",
]
