"""admin_logs query 过滤逻辑单测。

只测纯函数 _record_matches / _parse_line / _files_covering_range —
不起 FastAPI app,不连 DB。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from berry.channels.web.admin_logs import (
    _files_covering_range,
    _parse_line,
    _record_matches,
)


# ─── _parse_line ─────────────────────────────────────────


def test_parse_line_valid_json() -> None:
    line = '{"event":"x","level":"info","timestamp":"2026-06-13T00:00:00Z"}\n'
    rec = _parse_line(line)
    assert rec is not None
    assert rec["event"] == "x"


def test_parse_line_empty_returns_none() -> None:
    assert _parse_line("") is None
    assert _parse_line("\n") is None


def test_parse_line_bad_json_surfaces_as_unparsed() -> None:
    rec = _parse_line("garbled garbage not json\n")
    assert rec is not None
    assert rec["event"] == "_unparsed"
    assert rec["raw_text"] == "garbled garbage not json"


def test_parse_line_array_treated_as_unparsed() -> None:
    """JSON valid but not an object → still _unparsed."""
    rec = _parse_line("[1, 2, 3]\n")
    assert rec is not None
    assert rec["event"] == "_unparsed"


# ─── _record_matches ──────────────────────────────────────


def _rec(level: str = "info", event: str = "x", ts: str = "2026-06-13T12:00:00Z") -> dict:
    return {"level": level, "event": event, "timestamp": ts}


def test_match_no_filters() -> None:
    df = datetime(2026, 6, 13, tzinfo=UTC)
    dt = datetime(2026, 6, 14, tzinfo=UTC)
    assert _record_matches(_rec(), df, dt, levels=None, keyword=None)


def test_match_level_in_set() -> None:
    df = datetime(2026, 6, 13, tzinfo=UTC)
    dt = datetime(2026, 6, 14, tzinfo=UTC)
    assert _record_matches(_rec(level="error"), df, dt, levels={"ERROR"}, keyword=None)
    assert not _record_matches(_rec(level="info"), df, dt, levels={"ERROR"}, keyword=None)


def test_match_level_case_insensitive() -> None:
    df = datetime(2026, 6, 13, tzinfo=UTC)
    dt = datetime(2026, 6, 14, tzinfo=UTC)
    assert _record_matches(_rec(level="Error"), df, dt, levels={"ERROR"}, keyword=None)


def test_match_keyword_substring() -> None:
    df = datetime(2026, 6, 13, tzinfo=UTC)
    dt = datetime(2026, 6, 14, tzinfo=UTC)
    rec = {"level": "info", "event": "user_login", "user_id": "abc-123"}
    assert _record_matches(rec, df, dt, levels=None, keyword="abc")
    assert _record_matches(rec, df, dt, levels=None, keyword="LOGIN")  # case-insensitive
    assert not _record_matches(rec, df, dt, levels=None, keyword="zzz")


def test_match_time_range_excludes_outside() -> None:
    df = datetime(2026, 6, 13, 0, 0, tzinfo=UTC)
    dt = datetime(2026, 6, 13, 23, 59, tzinfo=UTC)
    assert _record_matches(
        _rec(ts="2026-06-13T12:00:00Z"), df, dt, levels=None, keyword=None
    )
    assert not _record_matches(
        _rec(ts="2026-06-12T12:00:00Z"), df, dt, levels=None, keyword=None
    )
    assert not _record_matches(
        _rec(ts="2026-06-14T12:00:00Z"), df, dt, levels=None, keyword=None
    )


def test_match_malformed_ts_does_not_drop() -> None:
    """坏 ts 不应该把整条记录丢掉 — 让 admin 看到。"""
    df = datetime(2026, 6, 13, tzinfo=UTC)
    dt = datetime(2026, 6, 14, tzinfo=UTC)
    assert _record_matches(_rec(ts="not-a-date"), df, dt, levels=None, keyword=None)


# ─── _files_covering_range ────────────────────────────────


def test_files_covering_range_picks_active_today(
    tmp_path: Path, monkeypatch
) -> None:
    """today 的范围应该挑到 berry.log(active)。"""
    from berry import config

    monkeypatch.setattr(config.settings, "log_dir", tmp_path)

    today = datetime.now(UTC).date()
    active = tmp_path / "berry.log"
    active.write_text("dummy")

    df = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    dt = datetime.combine(today, datetime.max.time(), tzinfo=UTC)
    files = _files_covering_range(df, dt)
    assert active in files


def test_files_covering_range_picks_gz_in_range(
    tmp_path: Path, monkeypatch
) -> None:
    from berry import config

    monkeypatch.setattr(config.settings, "log_dir", tmp_path)

    (tmp_path / "berry.log.2026-06-10.gz").write_text("g1")
    (tmp_path / "berry.log.2026-06-11.gz").write_text("g2")
    (tmp_path / "berry.log.2026-06-12.gz").write_text("g3")
    # 不该被选中
    (tmp_path / "berry.log.2026-06-05.gz").write_text("g_old")
    (tmp_path / "irrelevant.txt").write_text("nope")

    df = datetime(2026, 6, 11, tzinfo=UTC)
    dt = datetime(2026, 6, 12, 23, 59, tzinfo=UTC)
    files = _files_covering_range(df, dt)
    names = sorted(f.name for f in files)
    assert names == [
        "berry.log.2026-06-11.gz",
        "berry.log.2026-06-12.gz",
    ]


def test_files_covering_range_returns_newest_first(
    tmp_path: Path, monkeypatch
) -> None:
    from berry import config

    monkeypatch.setattr(config.settings, "log_dir", tmp_path)

    (tmp_path / "berry.log.2026-06-10.gz").write_text("g1")
    (tmp_path / "berry.log.2026-06-11.gz").write_text("g2")
    (tmp_path / "berry.log.2026-06-12.gz").write_text("g3")

    df = datetime(2026, 6, 10, tzinfo=UTC)
    dt = datetime(2026, 6, 12, 23, 59, tzinfo=UTC)
    files = _files_covering_range(df, dt)
    assert [f.name for f in files] == [
        "berry.log.2026-06-12.gz",
        "berry.log.2026-06-11.gz",
        "berry.log.2026-06-10.gz",
    ]
