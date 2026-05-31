"""ProjectService — 路径解析 + workspace 初始化。

所有「project 文件夹路径在哪」的问题,统一在这一层回答。
路径越界检查、mkdir 幂等、扩展点(domain-specific 子目录)都在这里。
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

from berry.core.db.models import Project
from berry.domain.errors import BerryError

# ─── 错误 ───────────────────────────────────────────────


class ProjectPathError(BerryError):
    """路径越界 / 非法 project name 等。"""


# ─── 校验 ───────────────────────────────────────────────

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def validate_project_name(name: str) -> None:
    """校验 project slug 形态。

    规则:小写字母数字下划线连字符,首字符必须字母数字,长度 1-63。
    """
    if not _NAME_RE.match(name):
        raise ProjectPathError(
            f"invalid project name {name!r}: must match {_NAME_RE.pattern!r}"
        )


# ─── 服务 ───────────────────────────────────────────────


class ProjectService:
    """路径解析 + workspace 初始化。

    Args:
        data_root: 来自 settings.data_root,所有路径相对它解析。

    业务代码不直接拼路径,统一调本服务。
    """

    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root.resolve()

    # ── 路径推导 ──

    def workspace_path(self, project: Project) -> Path:
        """返回 project workspace 的绝对路径。

        Project.workspace_path 字段在 DB 是相对路径(便于备份迁移),
        本方法返回绝对路径供文件操作。
        """
        rel = Path(project.workspace_path)
        full = (self._data_root / rel).resolve()
        self._assert_within_root(full)
        return full

    def workspace_path_for(self, user_id: UUID, project_name: str) -> Path:
        """供 create 时计算绝对路径(project 尚未入库)。"""
        validate_project_name(project_name)
        rel = Path("projects") / str(user_id) / project_name
        full = (self._data_root / rel).resolve()
        self._assert_within_root(full)
        return full

    def workspace_relative_path(self, user_id: UUID, project_name: str) -> str:
        """计算给 DB 落库的相对路径(POSIX 风格)。"""
        validate_project_name(project_name)
        return f"projects/{user_id}/{project_name}"

    # ── 子目录 ──

    def sessions_dir(self, project: Project) -> Path:
        """Session 文件存放目录。"""
        return self.workspace_path(project) / "sessions"

    def session_dir(self, project: Project, session_id: str) -> Path:
        """单个 session 的目录。"""
        return self.sessions_dir(project) / session_id

    def tasks_dir(self, project: Project) -> Path:
        """Task 文件存放目录。"""
        return self.workspace_path(project) / "tasks"

    def uploads_dir(self, project: Project) -> Path:
        """用户上传文件存放目录。"""
        return self.workspace_path(project) / "uploads"

    def domain_dir(self, project: Project) -> Path:
        """Domain-specific 子目录。例 learning project -> workspace/learning/"""
        return self.workspace_path(project) / project.domain

    # ── learning domain 专属 ──

    def learning_progress_file(self, project: Project) -> Path:
        """Learning domain 的进度文件路径。"""
        return self.domain_dir(project) / "progress.md"

    def learning_materials_dir(self, project: Project) -> Path:
        """Learning domain 的学习材料目录。"""
        return self.domain_dir(project) / "materials"

    # ── 初始化 ──

    def init_workspace(self, project: Project) -> None:
        """新建 project 时调用,mkdir 必要的子目录。

        幂等:已存在的目录跳过;不写任何文件(progress.md 等到 Agent 真用时才创建)。
        """
        ws = self.workspace_path(project)
        ws.mkdir(parents=True, exist_ok=True)
        self.sessions_dir(project).mkdir(exist_ok=True)
        self.tasks_dir(project).mkdir(exist_ok=True)
        self.uploads_dir(project).mkdir(exist_ok=True)

        if project.domain == "learning":
            self.learning_materials_dir(project).mkdir(parents=True, exist_ok=True)

    # ── 安全 ──

    def _assert_within_root(self, path: Path) -> None:
        """防 path traversal:确保解析后的路径仍在 data_root 下。"""
        try:
            path.resolve().relative_to(self._data_root)
        except ValueError as exc:
            raise ProjectPathError(
                f"path {path!r} escapes data_root {self._data_root!r}"
            ) from exc
