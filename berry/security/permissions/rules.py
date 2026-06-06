"""Rule-based permission checks. Each rule names the tools it applies to and
runs an ``args -> reason | None`` check; a non-None reason means
"this tool call needs user approval".

First-match-wins. Rules are pure functions; ``cwd`` is passed as the second
argument so a future rule could compare paths against the workspace root.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUSPICIOUS_BASH_TOKENS: tuple[str, ...] = (
    "rm ",
    "rm -",
    "> /etc/",
    ">> /etc/",
    "chmod 777",
    "chown ",
    "git push --force",
    "git push -f",
    "git reset --hard",
    "curl ",
    "wget ",
)


@dataclass(frozen=True)
class Rule:
    tools: frozenset[str]
    check: Callable[[dict[str, Any], Path], str | None]


def _bash_suspicious(args: dict[str, Any], _cwd: Path) -> str | None:
    cmd = args.get("command", "")
    if not isinstance(cmd, str):
        return None
    for t in SUSPICIOUS_BASH_TOKENS:
        if t in cmd:
            return f"contains {t!r}"
    return None


RULES: tuple[Rule, ...] = (
    Rule(frozenset({"bash"}), _bash_suspicious),
)


def check_rules(tool_name: str, args: dict[str, Any], cwd: Path) -> str | None:
    """First-match-wins. Returns reason string when a rule fires, else None."""
    for r in RULES:
        if tool_name not in r.tools:
            continue
        reason = r.check(args, cwd)
        if reason is not None:
            return reason
    return None
