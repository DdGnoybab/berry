"""文档服务 endpoints。

两个文档:
  - /v1/docs/user        — 主页用户指南(任何登录用户能看)
  - /v1/admin/docs/logs  — 日志面板使用指南(仅 admin)

为什么不直接走 nginx 静态? admin 那个要 role gate;统一从这里出更简单。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from berry.channels.web.auth.deps import AdminUser, require_admin

# repo root: berry/channels/web/docs.py 上溯 4 级
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCS_ROOT = _REPO_ROOT / "docs"


router = APIRouter(tags=["docs"])


def _read_doc(rel_path: str) -> str:
    """读 docs/<rel_path>,缺文件 / 越界 → 404。"""
    target = (_DOCS_ROOT / rel_path).resolve()
    # 防越界:必须落在 docs/ 内
    try:
        target.relative_to(_DOCS_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="doc not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="doc not found")
    return target.read_text(encoding="utf-8")


@router.get("/v1/docs/user", response_class=PlainTextResponse)
async def get_user_guide() -> str:
    """主页用户指南。任何登录用户(中间件已确保)。"""
    return _read_doc("user-guide.md")


@router.get("/v1/admin/docs/logs", response_class=PlainTextResponse)
async def get_logs_guide(admin: AdminUser = Depends(require_admin)) -> str:
    """日志面板使用指南。仅 admin。"""
    return _read_doc("admin/logs-guide.md")
