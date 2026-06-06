"""单元测试 ProjectService。

不需要真 DB:用 stub Project 实例,只测路径推导 / mkdir 幂等 / 路径越界。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from berry.core.db.models import Project
from berry.core.project.service import (
    ProjectPathError,
    ProjectService,
    validate_project_name,
)


def _make_project(
    *,
    user_id: UUID | None = None,
    name: str = "demo",
    domain: str = "learning",
    workspace_path: str | None = None,
) -> Project:
    """构造 stub Project,不挂 DB session。"""
    user_id = user_id or uuid4()
    workspace_path = workspace_path or f"projects/{user_id}/{name}"
    return Project(
        id=uuid4(),
        user_id=user_id,
        name=name,
        title=name.title(),
        domain=domain,
        workspace_path=workspace_path,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ─── validate_project_name ───────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["a", "abc", "abc-def", "abc_def", "abc123", "a" * 63],
)
def test_validate_project_name_accepts_valid(name: str) -> None:
    validate_project_name(name)  # no raise


@pytest.mark.parametrize(
    "name",
    [
        "",
        "A",          # 大写
        "_abc",       # 首字符是下划线
        "-abc",       # 首字符是连字符
        "ab c",       # 空格
        "ab/cd",      # 斜杠
        "../xx",      # path traversal
        "a" * 64,     # 长度超 63
    ],
)
def test_validate_project_name_rejects_invalid(name: str) -> None:
    with pytest.raises(ProjectPathError):
        validate_project_name(name)


# ─── ProjectService 路径推导 ─────────────────────────────


def test_workspace_path_returns_absolute_under_data_root(tmp_path: Path) -> None:
    svc = ProjectService(tmp_path)
    p = _make_project(name="redis")
    full = svc.workspace_path(p)

    assert full.is_absolute()
    assert full == (tmp_path / p.workspace_path).resolve()


def test_workspace_path_for_constructs_path(tmp_path: Path) -> None:
    svc = ProjectService(tmp_path)
    uid = uuid4()
    full = svc.workspace_path_for(uid, "redis")
    assert full == (tmp_path / "projects" / str(uid) / "redis").resolve()


def test_workspace_relative_path_is_posix_string(tmp_path: Path) -> None:
    svc = ProjectService(tmp_path)
    uid = uuid4()
    rel = svc.workspace_relative_path(uid, "redis")
    assert rel == f"projects/{uid}/redis"
    assert "\\" not in rel  # 不带 Windows 反斜杠


def test_subdirs_are_inside_workspace(tmp_path: Path) -> None:
    svc = ProjectService(tmp_path)
    p = _make_project(name="redis")
    ws = svc.workspace_path(p)

    assert svc.sessions_dir(p) == ws / "sessions"
    assert svc.session_dir(p, "20260601T000000-abcd") == ws / "sessions" / "20260601T000000-abcd"
    assert svc.tasks_dir(p) == ws / "tasks"
    assert svc.uploads_dir(p) == ws / "uploads"
    assert svc.domain_dir(p) == ws / "learning"


# ─── init_workspace ──────────────────────────────────────


def test_init_workspace_creates_dirs(tmp_path: Path) -> None:
    svc = ProjectService(tmp_path)
    p = _make_project(name="redis", domain="learning")

    svc.init_workspace(p)

    ws = svc.workspace_path(p)
    assert ws.is_dir()
    assert (ws / "sessions").is_dir()
    assert (ws / "tasks").is_dir()
    assert (ws / "uploads").is_dir()


def test_init_workspace_is_idempotent(tmp_path: Path) -> None:
    svc = ProjectService(tmp_path)
    p = _make_project(name="redis", domain="learning")

    svc.init_workspace(p)
    svc.init_workspace(p)  # 不抛错
    assert svc.workspace_path(p).is_dir()


def test_init_workspace_non_learning_skips_domain_dir(tmp_path: Path) -> None:
    svc = ProjectService(tmp_path)
    p = _make_project(name="myjob", domain="work")

    svc.init_workspace(p)

    ws = svc.workspace_path(p)
    assert ws.is_dir()
    # work domain 还没实现,init_workspace 不为它建子目录
    # 但 workspace 自己 + sessions / tasks / uploads 应该都建好
    assert (ws / "sessions").is_dir()
    assert not (ws / "learning").is_dir()  # 不该建别的 domain 的目录


# ─── 路径越界保护 ───────────────────────────────────────


def test_workspace_path_traversal_blocked(tmp_path: Path) -> None:
    svc = ProjectService(tmp_path)
    # 构造一个恶意 workspace_path 试图逃出 data_root
    p = _make_project(name="x", workspace_path="../../etc")

    with pytest.raises(ProjectPathError):
        svc.workspace_path(p)
