"""FastAPI dependencies for auth-gated routes.

`AuthMiddleware` 已经把 `user_id` 塞进 `request.state`,这里在它基础上加角色校验。

用法:
    from fastapi import Depends
    from berry.channels.web.auth.deps import require_admin, AdminUser

    @router.get("/v1/admin/something")
    async def something(admin: AdminUser = Depends(require_admin)) -> ...:
        ...
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select

from berry.core.db.models import User
from berry.core.db.session import async_session_factory


@dataclass(frozen=True)
class AdminUser:
    """admin 路由 dep 解析后的轻量数据。

    不暴露 ORM 行,只把后续 handler 真正用得到的字段拷过来。
    """

    user_id: UUID
    role: str


async def require_admin(request: Request) -> AdminUser:
    """admin-only 路由的 FastAPI dependency。

    顺序:
      1. 中间件已经检查过 cookie,user_id 已经塞 request.state(否则早 401 了)
      2. 这里只查角色 — DB 查一次,不缓存(admin 角色变化罕见,简单优先)
      3. role != 'admin' → 403,前端拿到 403 再做 redirect

    Raises:
        HTTPException(401): user_id 缺失(理论上中间件兜底,这里防御)
        HTTPException(403): user_id 存在但 role != 'admin'
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="not authenticated")

    async with async_session_factory() as db:
        row = (
            await db.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=401, detail="user not found")
    if row.role != "admin":
        raise HTTPException(status_code=403, detail="admin only")

    return AdminUser(user_id=row.id, role=row.role)
