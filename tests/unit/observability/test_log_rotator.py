"""日志轮转 + gzip 压缩 + 保留期清理 单测。

不调真的 logger,只测 _gzip_rotator 和 TimedRotatingFileHandler 的协作。
"""

from __future__ import annotations

import gzip
from pathlib import Path

from berry.observability.logging import _gzip_rotator


def test_gzip_rotator_compresses_and_removes_source(tmp_path: Path) -> None:
    src = tmp_path / "berry.log.2026-06-12"
    src.write_text("line1\nline2\n", encoding="utf-8")
    dst = tmp_path / "berry.log.2026-06-12.gz"

    _gzip_rotator(str(src), str(dst))

    assert not src.exists(), "源文件应被删除"
    assert dst.exists(), "gz 文件应被创建"
    with gzip.open(dst, "rt", encoding="utf-8") as f:
        assert f.read() == "line1\nline2\n"


def test_add_file_sink_creates_log_dir(tmp_path: Path) -> None:
    """log_dir 不存在时应自动创建。"""
    from berry.observability.logging import _add_file_sink

    log_dir = tmp_path / "logs"
    assert not log_dir.exists()

    _add_file_sink(log_dir, retention_days=7)

    assert log_dir.is_dir()


def test_add_file_sink_writes_message(tmp_path: Path) -> None:
    """挂上 handler 后,普通 logging.info() 应该写到 berry.log。"""
    import logging

    from berry.observability.logging import _add_file_sink

    log_dir = tmp_path / "logs"
    _add_file_sink(log_dir, retention_days=7)

    # root logger 默认 WARNING,显式提到 INFO 才能让 info() 真的写下去
    root = logging.getLogger()
    saved_level = root.level
    root.setLevel(logging.INFO)
    try:
        root.info("rotator_test_marker")
        for h in root.handlers:
            h.flush()
    finally:
        root.setLevel(saved_level)

    log_file = log_dir / "berry.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "rotator_test_marker" in content
