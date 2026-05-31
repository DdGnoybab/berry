"""progress.md 解析 / 写回。

格式:
    ---
    <YAML frontmatter>
    ---
    <markdown body>

frontmatter 由 Agent / 用户改,body 是用户可读的概览。
schema_version 字段允许未来字段升级。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ─── 错误 ──────────────────────────────────────────────


class ProgressFormatError(Exception):
    """progress.md 格式不合法。"""


# ─── 数据类 ─────────────────────────────────────────────


@dataclass
class ProgressDocument:
    """parse 后的 progress.md。

    frontmatter 是 dict[str, Any](字段在 schema 文档里定义,本层不强校验,
    domain handler 自己负责语义)。body 是 markdown 原文(不含 ---)。
    """

    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    def to_text(self) -> str:
        """序列化回完整 progress.md 文本。

        frontmatter 用 yaml 序列化,allow_unicode=True 让中文不转义,
        sort_keys=False 保持字段顺序。
        """
        fm_yaml = yaml.dump(
            self.frontmatter,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        # 处理 body:确保单换行结尾
        body = self.body.rstrip() + "\n" if self.body.strip() else ""
        return f"---\n{fm_yaml}---\n\n{body}" if body else f"---\n{fm_yaml}---\n"


# ─── 解析 / 写回 ────────────────────────────────────────


def parse(text: str) -> ProgressDocument:
    """解析 progress.md 文本。

    - 没有 frontmatter(没有 `---` 包围)→ frontmatter 为 {},body 为整个文本
    - 解析失败 → 抛 ProgressFormatError
    """
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return ProgressDocument(frontmatter={}, body=text)

    # 切 frontmatter:从第二行开始找 `---` 结束
    lines = text.splitlines(keepends=True)
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == "---":
            end_idx = i
            break
    if end_idx is None:
        raise ProgressFormatError(
            "progress.md frontmatter not closed (missing trailing ---)"
        )

    fm_text = "".join(lines[1:end_idx])
    body = "".join(lines[end_idx + 1 :]).lstrip("\n")

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ProgressFormatError(f"invalid YAML frontmatter: {exc}") from exc

    if not isinstance(fm, dict):
        raise ProgressFormatError(
            f"frontmatter must be a YAML mapping, got {type(fm).__name__}"
        )

    return ProgressDocument(frontmatter=fm, body=body)


def read(path: Path) -> ProgressDocument:
    """读 progress.md 文件。

    文件不存在 → 返回空 document(frontmatter={}, body=""),不抛错(让上层
    自行决定怎么处理「project 还没初始化」)。
    """
    if not path.exists():
        return ProgressDocument()
    return parse(path.read_text(encoding="utf-8"))


def write(path: Path, doc: ProgressDocument) -> None:
    """原子写 progress.md(temp + rename)。

    防止半写状态被 Agent 读到。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(doc.to_text(), encoding="utf-8")
    tmp.replace(path)


# ─── frontmatter 工具 ───────────────────────────────────


def init_empty_frontmatter(project_name: str, domain: str) -> dict[str, Any]:
    """新 project 第一次创建 progress.md 时的初始 frontmatter。"""
    return {
        "schema_version": 1,
        "project_name": project_name,
        "domain": domain,
        "goals": [],
        "last_active": None,
    }
