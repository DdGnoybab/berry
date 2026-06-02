"""TDD tests for session_log_parser.py.

Parses SESSION_LOG.md (an append-only learning journal) into a list of
:class:`SessionLogEntry`. Format spec:
  docs/superpowers/specs/2026-06-01-learning-loop-product-design.md (revised
  in dogfood iteration §6.4 — "Session continuity")

Same tolerance philosophy as progress_parser: garbage in returns []
rather than crashing the prompt build.
"""

from __future__ import annotations

import pytest

from berry.assistants.learning.prompts.session_log_parser import (
    SessionLogEntry,
    parse_session_log_md,
)


# ─── Happy path ────────────────────────────────────────────────────────────


def test_parses_single_entry() -> None:
    content = """\
# Session log

## 2026-06-01 14:40 (session 20260601T144042)
- Milestone 1, small goal 1.2 (redis-cli 基本操作)
- Did: SET/GET/DEL/EXISTS/EXPIRE/TTL with focus on EXPIRE 覆盖语义
- Quiz score: 4/10 — failed: EXPIRE 覆盖, RTT
- Pending: review-and-retest
- User signal: 觉得题难度合适
"""
    entries = parse_session_log_md(content)
    assert len(entries) == 1
    e = entries[0]
    assert e.timestamp == "2026-06-01 14:40"
    assert e.session_id == "20260601T144042"
    assert "Milestone 1, small goal 1.2" in e.body
    assert e.has_pending is True


def test_parses_multiple_entries_in_order() -> None:
    content = """\
# Session log

## 2026-06-01 14:40 (session aaa)
- did some stuff

## 2026-06-01 21:15 (session bbb)
- did more stuff

## 2026-06-02 10:00 (session ccc)
- did even more
"""
    entries = parse_session_log_md(content)
    assert len(entries) == 3
    assert [e.session_id for e in entries] == ["aaa", "bbb", "ccc"]


def test_detects_pending_marker() -> None:
    content = """\
## 2026-06-01 14:40 (session a)
- did x
- Pending: come back to EXPIRE
"""
    entries = parse_session_log_md(content)
    assert entries[0].has_pending is True


def test_detects_no_pending_when_absent() -> None:
    content = """\
## 2026-06-01 14:40 (session a)
- did x
- all good
"""
    entries = parse_session_log_md(content)
    assert entries[0].has_pending is False


def test_detects_issue_marker_as_pending() -> None:
    """Both 'Pending:' and 'Issue:' should mark as needing follow-up."""
    content = """\
## 2026-06-01 14:40 (session a)
- did x
- Issue: 用户对 RDB fork 有大误解
"""
    entries = parse_session_log_md(content)
    assert entries[0].has_pending is True


# ─── Edge cases ────────────────────────────────────────────────────────────


def test_returns_empty_for_empty_content() -> None:
    assert parse_session_log_md("") == []


def test_returns_empty_for_no_h2_headers() -> None:
    """Just header text, no entries → empty list, no crash."""
    content = "# Session log\n\nNothing yet.\n"
    assert parse_session_log_md(content) == []


def test_skips_malformed_entry_headers() -> None:
    """An H2 without 'session ...' suffix is ignored."""
    content = """\
## just some random heading
body here

## 2026-06-01 14:40 (session abc)
- valid entry
"""
    entries = parse_session_log_md(content)
    assert len(entries) == 1
    assert entries[0].session_id == "abc"


# ─── Helper: latest N ──────────────────────────────────────────────────────


def test_entries_can_be_sliced_for_recent() -> None:
    """Caller will use entries[-N:] to get last N — ensure parser preserves order."""
    content = "\n".join(
        f"## 2026-06-{i:02d} 10:00 (session s{i})\n- entry {i}\n"
        for i in range(1, 11)
    )
    entries = parse_session_log_md(content)
    last_5 = entries[-5:]
    assert [e.session_id for e in last_5] == ["s6", "s7", "s8", "s9", "s10"]
