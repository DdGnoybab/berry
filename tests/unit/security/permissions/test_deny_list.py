"""Tests for deny_list — hard-block patterns for bash."""

from __future__ import annotations

import pytest

from berry.security.permissions.deny_list import check_deny


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -rf /*",
        "rm -rf ~",
        "rm -rf $HOME",
        "sudo apt install foo",
        "shutdown -h now",
        "reboot",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        ":(){ :|:& };:",
        "echo hello && rm -rf / && echo done",  # substring match still hits
    ],
)
def test_check_deny_matches_dangerous_commands(command: str) -> None:
    assert check_deny(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "rm foo.py",                  # plain rm — handled by rules, not deny
        "ls /etc/",
        "git status",
        "",
    ],
)
def test_check_deny_skips_safe_commands(command: str) -> None:
    assert check_deny(command) is None


def test_rm_rf_with_path_under_root_still_denies() -> None:
    """Documented limitation: substring match means `rm -rf /tmp/build` also
    matches `rm -rf /`. We treat that as the safer side (deny anything that
    looks like wiping root). True path discrimination requires a real shell
    parser, which is the Sandbox Protocol's job."""
    assert check_deny("rm -rf /tmp/build") == "rm -rf /"


def test_check_deny_returns_matched_pattern() -> None:
    matched = check_deny("rm -rf / now")
    assert matched == "rm -rf /"
