"""文档 endpoint 的纯函数 / 路径安全测试。

用 FastAPI 起 app 测路由太重 — _read_doc 是单纯文件读取,
直接覆盖路径越界 / 缺失 / 正常三种情况就够。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from berry.channels.web import docs as docs_module


def test_read_doc_returns_file_content(tmp_path: Path, monkeypatch) -> None:
    """正常路径:读到内容。"""
    fake_docs = tmp_path / "docs"
    fake_docs.mkdir()
    (fake_docs / "user-guide.md").write_text("# Hello", encoding="utf-8")

    monkeypatch.setattr(docs_module, "_DOCS_ROOT", fake_docs)
    out = docs_module._read_doc("user-guide.md")
    assert out == "# Hello"


def test_read_doc_subdir(tmp_path: Path, monkeypatch) -> None:
    """子目录文件可读 — admin/logs-guide.md 这种。"""
    fake_docs = tmp_path / "docs"
    (fake_docs / "admin").mkdir(parents=True)
    (fake_docs / "admin" / "logs-guide.md").write_text("logs!", encoding="utf-8")

    monkeypatch.setattr(docs_module, "_DOCS_ROOT", fake_docs)
    assert docs_module._read_doc("admin/logs-guide.md") == "logs!"


def test_read_doc_missing_returns_404(tmp_path: Path, monkeypatch) -> None:
    fake_docs = tmp_path / "docs"
    fake_docs.mkdir()
    monkeypatch.setattr(docs_module, "_DOCS_ROOT", fake_docs)

    with pytest.raises(HTTPException) as exc_info:
        docs_module._read_doc("nope.md")
    assert exc_info.value.status_code == 404


def test_read_doc_traversal_blocked(tmp_path: Path, monkeypatch) -> None:
    """`..` 越界 → 404,不能读 docs/ 之外。"""
    fake_docs = tmp_path / "docs"
    fake_docs.mkdir()
    # 在 docs 同级放个 secret 文件
    secret = tmp_path / "secret.md"
    secret.write_text("DO NOT LEAK", encoding="utf-8")

    monkeypatch.setattr(docs_module, "_DOCS_ROOT", fake_docs)

    with pytest.raises(HTTPException) as exc_info:
        docs_module._read_doc("../secret.md")
    assert exc_info.value.status_code == 404


def test_real_docs_files_exist() -> None:
    """生产用的两份 md 必须真实存在。"""
    repo_root = Path(__file__).resolve().parents[4]
    assert (repo_root / "docs" / "user-guide.md").is_file()
    assert (repo_root / "docs" / "admin" / "logs-guide.md").is_file()
