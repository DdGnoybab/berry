"""单元测试 progress.md 解析 / 写回。"""

from __future__ import annotations

from pathlib import Path

import pytest

from berry.core.project.progress import (
    ProgressDocument,
    ProgressFormatError,
    init_empty_frontmatter,
    parse,
    read,
    write,
)

# ─── parse ───────────────────────────────────────────────


def test_parse_with_frontmatter() -> None:
    text = """---
schema_version: 1
project_name: redis
goals:
  - id: g1
    title: 入门
    status: completed
---

# Redis 学习计划

## g1. 入门
"""
    doc = parse(text)
    assert doc.frontmatter["schema_version"] == 1
    assert doc.frontmatter["project_name"] == "redis"
    assert doc.frontmatter["goals"][0]["title"] == "入门"
    assert doc.body.startswith("# Redis 学习计划")


def test_parse_without_frontmatter_returns_empty_fm() -> None:
    text = "Just markdown body, no frontmatter\n"
    doc = parse(text)
    assert doc.frontmatter == {}
    assert doc.body == text


def test_parse_empty_string() -> None:
    doc = parse("")
    assert doc.frontmatter == {}
    assert doc.body == ""


def test_parse_unclosed_frontmatter_raises() -> None:
    text = "---\nschema_version: 1\n# nothing closes the fm"
    with pytest.raises(ProgressFormatError, match="not closed"):
        parse(text)


def test_parse_invalid_yaml_raises() -> None:
    text = "---\nfoo: [unclosed\n---\nbody\n"
    with pytest.raises(ProgressFormatError, match="invalid YAML"):
        parse(text)


def test_parse_frontmatter_not_mapping_raises() -> None:
    text = "---\n- 1\n- 2\n---\nbody\n"
    with pytest.raises(ProgressFormatError, match="must be a YAML mapping"):
        parse(text)


def test_parse_handles_crlf_line_endings() -> None:
    text = "---\r\nfoo: bar\r\n---\r\nbody\r\n"
    doc = parse(text)
    assert doc.frontmatter == {"foo": "bar"}


# ─── to_text round-trip ────────────────────────────────


def test_round_trip_preserves_content() -> None:
    original = ProgressDocument(
        frontmatter={
            "schema_version": 1,
            "project_name": "redis",
            "goals": [{"id": "g1", "title": "入門", "status": "completed"}],
        },
        body="# Redis 学习计划\n\n正文内容",
    )
    serialized = original.to_text()
    parsed = parse(serialized)

    assert parsed.frontmatter == original.frontmatter
    # body 可能有末尾空白调整,但语义一致
    assert "Redis 学习计划" in parsed.body
    assert "正文内容" in parsed.body


def test_to_text_preserves_unicode() -> None:
    doc = ProgressDocument(
        frontmatter={"title": "中文标题"}, body="中文正文"
    )
    out = doc.to_text()
    assert "中文标题" in out
    assert "中文正文" in out


def test_to_text_empty_body() -> None:
    doc = ProgressDocument(frontmatter={"x": 1}, body="")
    out = doc.to_text()
    assert "x: 1" in out
    assert out.endswith("---\n")


# ─── read / write 文件 ──────────────────────────────────


def test_read_nonexistent_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "progress.md"
    doc = read(p)
    assert doc.frontmatter == {}
    assert doc.body == ""


def test_write_then_read(tmp_path: Path) -> None:
    p = tmp_path / "subdir" / "progress.md"
    doc = ProgressDocument(
        frontmatter={"schema_version": 1, "goals": []},
        body="# Hello",
    )
    write(p, doc)

    assert p.exists()
    assert p.parent.is_dir()

    loaded = read(p)
    assert loaded.frontmatter == doc.frontmatter
    assert "Hello" in loaded.body


def test_write_is_atomic(tmp_path: Path) -> None:
    """写完后 .tmp 文件应该不存在(已 rename 成正式名)。"""
    p = tmp_path / "progress.md"
    write(p, ProgressDocument(frontmatter={"a": 1}))
    assert p.exists()
    assert not p.with_suffix(p.suffix + ".tmp").exists()


# ─── init_empty_frontmatter ─────────────────────────────


def test_init_empty_frontmatter_has_required_fields() -> None:
    fm = init_empty_frontmatter("redis", "learning")
    assert fm["schema_version"] == 1
    assert fm["project_name"] == "redis"
    assert fm["domain"] == "learning"
    assert fm["goals"] == []
    assert fm["last_active"] is None
