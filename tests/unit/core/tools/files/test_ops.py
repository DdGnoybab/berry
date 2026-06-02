"""TDD tests for ops.py — pure file IO functions.

Mirrors claw-code (file_ops.rs::read_file / write_file / edit_file) plus
berry's one deliberate divergence (edit_file rejects multi-match when
replace_all is false; see spec § 11 ADR).

Output schemas match claw-code's JSON envelopes (camelCase keys).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from berry.core.tools.files.ops import (
    MAX_READ_SIZE,
    MAX_WRITE_SIZE,
    edit_file_in_workspace,
    read_file_in_workspace,
    write_file_in_workspace,
)
from berry.domain.errors import FileScopeError


# ─── read_file_in_workspace ────────────────────────────────────────────────


def test_read_returns_full_content_with_metadata(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("line1\nline2\nline3\n")

    result = read_file_in_workspace("a.md", offset=None, limit=None, workspace=tmp_path)

    assert result["type"] == "text"
    assert result["file"]["filePath"] == str(file.resolve())
    assert result["file"]["content"] == "line1\nline2\nline3"
    assert result["file"]["numLines"] == 3
    assert result["file"]["startLine"] == 1
    assert result["file"]["totalLines"] == 3


def test_read_with_offset_skips_lines(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("a\nb\nc\nd\n")

    result = read_file_in_workspace("a.md", offset=2, limit=None, workspace=tmp_path)
    assert result["file"]["content"] == "c\nd"
    assert result["file"]["startLine"] == 3
    assert result["file"]["numLines"] == 2
    assert result["file"]["totalLines"] == 4


def test_read_with_limit_caps_lines(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("a\nb\nc\nd\ne\n")

    result = read_file_in_workspace("a.md", offset=None, limit=2, workspace=tmp_path)
    assert result["file"]["content"] == "a\nb"
    assert result["file"]["numLines"] == 2
    assert result["file"]["totalLines"] == 5


def test_read_with_offset_and_limit(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("\n".join(str(i) for i in range(10)) + "\n")

    result = read_file_in_workspace("a.md", offset=3, limit=4, workspace=tmp_path)
    assert result["file"]["content"] == "3\n4\n5\n6"


def test_read_offset_beyond_eof_returns_empty(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("a\nb\n")

    result = read_file_in_workspace("a.md", offset=99, limit=10, workspace=tmp_path)
    assert result["file"]["content"] == ""
    assert result["file"]["numLines"] == 0
    assert result["file"]["totalLines"] == 2


def test_read_rejects_outside_workspace(tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / "other-ws-read"
    outside_dir.mkdir(exist_ok=True)
    target = outside_dir / "secret.md"
    target.write_text("nuclear codes")

    with pytest.raises(FileScopeError):
        read_file_in_workspace(str(target), offset=None, limit=None, workspace=tmp_path)


def test_read_rejects_oversized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use a tiny override to keep the test fast."""
    monkeypatch.setattr("berry.core.tools.files.ops.MAX_READ_SIZE", 16)
    file = tmp_path / "big.md"
    file.write_text("x" * 32)
    with pytest.raises(OSError, match="too large"):
        read_file_in_workspace("big.md", None, None, workspace=tmp_path)


def test_read_rejects_binary(tmp_path: Path) -> None:
    file = tmp_path / "image.bin"
    file.write_bytes(b"PNG\x00\x00binary garbage")
    with pytest.raises(OSError, match="binary"):
        read_file_in_workspace("image.bin", None, None, workspace=tmp_path)


def test_read_max_size_constant_matches_spec() -> None:
    """Sanity: ops module exposes the 10MB cap claw-code uses."""
    assert MAX_READ_SIZE == 10 * 1024 * 1024


# ─── write_file_in_workspace ───────────────────────────────────────────────


def test_write_creates_new_file(tmp_path: Path) -> None:
    result = write_file_in_workspace("new.md", "hello", workspace=tmp_path)

    target = tmp_path / "new.md"
    assert target.read_text() == "hello"
    assert result["type"] == "create"
    assert result["filePath"] == str(target.resolve())
    assert result["content"] == "hello"
    assert result["originalFile"] is None
    assert result["gitDiff"] is None
    assert isinstance(result["structuredPatch"], list)
    assert len(result["structuredPatch"]) == 1


def test_write_overwrites_existing_file(tmp_path: Path) -> None:
    existing = tmp_path / "x.md"
    existing.write_text("old content")

    result = write_file_in_workspace("x.md", "new content", workspace=tmp_path)

    assert existing.read_text() == "new content"
    assert result["type"] == "update"
    assert result["originalFile"] == "old content"


def test_write_creates_missing_parents(tmp_path: Path) -> None:
    result = write_file_in_workspace(
        "deep/nested/dir/x.md", "ok", workspace=tmp_path,
    )
    target = tmp_path / "deep" / "nested" / "dir" / "x.md"
    assert target.read_text() == "ok"
    assert result["type"] == "create"


def test_write_rejects_outside_workspace(tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / "other-ws-write"
    outside_dir.mkdir(exist_ok=True)
    with pytest.raises(FileScopeError):
        write_file_in_workspace(
            str(outside_dir / "leaked.md"), "evil", workspace=tmp_path,
        )


def test_write_rejects_oversized_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("berry.core.tools.files.ops.MAX_WRITE_SIZE", 16)
    with pytest.raises(OSError, match="too large"):
        write_file_in_workspace("big.md", "x" * 32, workspace=tmp_path)


def test_write_max_size_constant_matches_spec() -> None:
    assert MAX_WRITE_SIZE == 10 * 1024 * 1024


# ─── edit_file_in_workspace ────────────────────────────────────────────────


def test_edit_replaces_unique_old_string(tmp_path: Path) -> None:
    file = tmp_path / "x.md"
    file.write_text("hello world\nbye world\n")

    result = edit_file_in_workspace(
        "x.md", old_string="hello", new_string="hi",
        replace_all=False, workspace=tmp_path,
    )

    assert file.read_text() == "hi world\nbye world\n"
    assert result["filePath"] == str(file.resolve())
    assert result["oldString"] == "hello"
    assert result["newString"] == "hi"
    assert result["originalFile"] == "hello world\nbye world\n"
    assert result["replaceAll"] is False
    assert result["userModified"] is False
    assert result["gitDiff"] is None


def test_edit_rejects_old_equals_new(tmp_path: Path) -> None:
    file = tmp_path / "x.md"
    file.write_text("hello\n")
    with pytest.raises(ValueError, match="must differ"):
        edit_file_in_workspace(
            "x.md", old_string="hello", new_string="hello",
            replace_all=False, workspace=tmp_path,
        )


def test_edit_rejects_old_not_in_file(tmp_path: Path) -> None:
    file = tmp_path / "x.md"
    file.write_text("hello\n")
    with pytest.raises(ValueError, match="not found"):
        edit_file_in_workspace(
            "x.md", old_string="missing", new_string="ok",
            replace_all=False, workspace=tmp_path,
        )


def test_edit_rejects_multi_match_when_not_replace_all(tmp_path: Path) -> None:
    """Spec § 11 ADR — berry differs from claw-code here on purpose."""
    file = tmp_path / "x.md"
    file.write_text("foo\nfoo\nfoo\n")
    with pytest.raises(ValueError, match="appears 3 times"):
        edit_file_in_workspace(
            "x.md", old_string="foo", new_string="bar",
            replace_all=False, workspace=tmp_path,
        )


def test_edit_replace_all_replaces_every_occurrence(tmp_path: Path) -> None:
    file = tmp_path / "x.md"
    file.write_text("foo\nfoo\nbaz\nfoo\n")

    result = edit_file_in_workspace(
        "x.md", old_string="foo", new_string="bar",
        replace_all=True, workspace=tmp_path,
    )

    assert file.read_text() == "bar\nbar\nbaz\nbar\n"
    assert result["replaceAll"] is True


def test_edit_rejects_outside_workspace(tmp_path: Path) -> None:
    outside_dir = tmp_path.parent / "other-ws-edit"
    outside_dir.mkdir(exist_ok=True)
    target = outside_dir / "secret.md"
    target.write_text("hello")

    with pytest.raises(FileScopeError):
        edit_file_in_workspace(
            str(target), old_string="hello", new_string="x",
            replace_all=False, workspace=tmp_path,
        )


def test_edit_returns_structured_patch(tmp_path: Path) -> None:
    file = tmp_path / "x.md"
    file.write_text("foo bar\n")

    result = edit_file_in_workspace(
        "x.md", old_string="foo", new_string="qux",
        replace_all=False, workspace=tmp_path,
    )

    patch = result["structuredPatch"]
    assert isinstance(patch, list)
    assert len(patch) == 1
    hunk = patch[0]
    assert hunk["oldStart"] == 1
    assert hunk["newStart"] == 1
    assert any(line.startswith("-") for line in hunk["lines"])
    assert any(line.startswith("+") for line in hunk["lines"])
