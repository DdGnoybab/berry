"""Tests for rules — ask-user permission gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from berry.security.permissions.rules import check_rules

CWD = Path("/tmp/berry_test")


@pytest.mark.parametrize(
    "command",
    [
        "rm foo.py",
        "rm -f bar.txt",
        "echo hi > /etc/hosts",
        "chmod 777 /tmp/foo",
        "chown bbb file",
        "git push --force",
        "git push -f origin main",
        "git reset --hard HEAD~1",
        "curl https://example.com",
        "wget http://example.com/x",
    ],
)
def test_bash_suspicious_command_triggers_rule(command: str) -> None:
    reason = check_rules("bash", {"command": command}, CWD)
    assert reason is not None


@pytest.mark.parametrize(
    "command",
    [
        "ls",
        "cat foo.txt",
        "echo hello",
        "git status",
        "python script.py",
    ],
)
def test_bash_safe_command_does_not_trigger_rule(command: str) -> None:
    assert check_rules("bash", {"command": command}, CWD) is None


def test_non_bash_tool_returns_none() -> None:
    assert check_rules("write_file", {"path": "/etc/passwd"}, CWD) is None
    assert check_rules("read_file", {"path": "anywhere"}, CWD) is None


def test_bash_missing_command_returns_none() -> None:
    assert check_rules("bash", {}, CWD) is None


def test_bash_non_string_command_returns_none() -> None:
    """Robustness: don't crash on weird args; just return None."""
    assert check_rules("bash", {"command": 123}, CWD) is None


def test_reason_includes_matched_token() -> None:
    reason = check_rules("bash", {"command": "rm foo"}, CWD)
    assert reason is not None
    assert "rm " in reason
