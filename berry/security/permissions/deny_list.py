"""Hard-deny patterns for bash. Substring match.

Substring matching is NOT a security boundary — variable expansion / aliases /
word splitting can bypass. This list is a guardrail against well-intentioned
LLM mistakes, not a sandbox. Real isolation is the Sandbox Protocol's job
(Task #1 in the project roadmap).
"""

from __future__ import annotations

DENY_PATTERNS: tuple[str, ...] = (
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf $HOME",
    "sudo ",
    "shutdown",
    "reboot",
    "mkfs",
    "dd if=",
    "> /dev/sda",
    ":(){ :|:& };:",
)


def check_deny(command: str) -> str | None:
    """Return the matched pattern when blocked, else None."""
    for p in DENY_PATTERNS:
        if p in command:
            return p
    return None
