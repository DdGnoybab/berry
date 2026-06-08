"""Auth endpoints: /auth/login / /auth/logout / /auth/me.

/auth/login  — POST {username, password} → set cookie + return user info
/auth/logout — POST → delete server-side session row + clear cookie
/auth/me     — GET  → current user info (requires valid cookie)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from berry.channels.web.auth.middleware import COOKIE_NAME
from berry.channels.web.auth.passwords import verify_password
from berry.channels.web.auth.repo import AuthSessionRepo
from berry.channels.web.auth.tokens import generate_token, hash_token
from berry.config import settings
from berry.core.db.repos.user_repo import UserRepo
from berry.core.db.session import async_session_factory

router = APIRouter(tags=["auth"])

WEB_HANDLE_PREFIX = "web:"


def _web_handle(username: str) -> str:
    return f"{WEB_HANDLE_PREFIX}{username}"


# ─── schemas ─────────────────────────────────────────────


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user_id: str
    username: str


class MeResponse(BaseModel):
    user_id: str
    username: str
    display_name: str


# ─── routes ──────────────────────────────────────────────


@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, response: Response) -> LoginResponse:
    handle = _web_handle(req.username)
    async with async_session_factory() as db:
        user = await UserRepo(db).get_by_handle(handle)
        if user is None:
            raise HTTPException(status_code=401, detail="invalid credentials")
        password_hash = (user.metadata_ or {}).get("password_hash", "")
        if not verify_password(req.password, password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")

        raw_token = generate_token()
        token_hash_value = hash_token(raw_token)
        expires_at = datetime.now(UTC) + timedelta(days=settings.session_ttl_days)
        await AuthSessionRepo(db).create(
            user_id=user.id,
            token_hash=token_hash_value,
            expires_at=expires_at,
        )

    response.set_cookie(
        key=COOKIE_NAME,
        value=raw_token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return LoginResponse(user_id=str(user.id), username=req.username)


@router.post("/auth/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        token_hash_value = hash_token(token)
        async with async_session_factory() as db:
            await AuthSessionRepo(db).delete_by_token_hash(token_hash_value)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/auth/me", response_model=MeResponse)
async def me(request: Request) -> MeResponse:
    """Returns current user. Middleware has already validated the cookie."""
    from sqlalchemy import select

    from berry.core.db.models import User

    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="not authenticated")

    async with async_session_factory() as db:
        row = (
            await db.execute(select(User).where(User.id == user_id))  # type: ignore[arg-type]
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="user not found")

    username = row.handle.removeprefix(WEB_HANDLE_PREFIX)
    return MeResponse(
        user_id=str(row.id),
        username=username,
        display_name=row.display_name,
    )
