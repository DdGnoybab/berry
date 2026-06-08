"""Admin subcommands for managing web users.

Usage:
  berry-cli user create <username>          — create a web user, print generated password
  berry-cli user list                       — list all web:* users
  berry-cli user reset-password <username>  — reset password, force logout, print new password
  berry-cli user delete <username>          — delete user (cascades to sessions / projects)

These commands talk to PG directly. They are *not* part of the REPL.
"""

from __future__ import annotations

import asyncio
import secrets
import sys

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from berry.channels.web.auth.passwords import hash_password
from berry.channels.web.auth.repo import AuthSessionRepo
from berry.channels.web.auth.routes import WEB_HANDLE_PREFIX
from berry.core.db.models import User
from berry.core.db.session import async_session_factory, engine

PASSWORD_LENGTH_BYTES = 9  # → 12 char URL-safe string


def _gen_password() -> str:
    return secrets.token_urlsafe(PASSWORD_LENGTH_BYTES)


def _web_handle(username: str) -> str:
    return f"{WEB_HANDLE_PREFIX}{username}"


# ─── command bodies ──────────────────────────────────────


async def _create(username: str) -> int:
    handle = _web_handle(username)
    async with async_session_factory() as db:
        existing = await _get_by_handle(db, handle)
        if existing is not None:
            print(f"error: user '{username}' already exists", file=sys.stderr)
            return 1

        password = _gen_password()
        user = User(
            handle=handle,
            display_name=username,
            metadata_={"password_hash": hash_password(password)},
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    print(f"Generated password: {password}")
    print(f"Account ready. handle={handle} user_id={user.id}")
    return 0


async def _list() -> int:
    async with async_session_factory() as db:
        result = await db.execute(
            select(User).where(User.handle.like(f"{WEB_HANDLE_PREFIX}%"))  # type: ignore[attr-defined]
        )
        rows = list(result.scalars().all())

    if not rows:
        print("(no web users)")
        return 0

    print(f"{'username':<24} {'user_id':<38} created_at")
    for row in rows:
        username = row.handle.removeprefix(WEB_HANDLE_PREFIX)
        print(f"{username:<24} {str(row.id):<38} {row.created_at.isoformat()}")
    return 0


async def _reset_password(username: str) -> int:
    handle = _web_handle(username)
    async with async_session_factory() as db:
        user = await _get_by_handle(db, handle)
        if user is None:
            print(f"error: user '{username}' not found", file=sys.stderr)
            return 1

        password = _gen_password()
        # JSONB 整字段更新 — 触发 SQLAlchemy 检测变更
        new_meta = dict(user.metadata_ or {})
        new_meta["password_hash"] = hash_password(password)
        user.metadata_ = new_meta
        db.add(user)
        await db.commit()

        # 强制下线该用户所有设备
        await AuthSessionRepo(db).delete_all_for_user(user.id)

    print(f"Generated password: {password}")
    print(f"All existing sessions revoked for {username}.")
    return 0


async def _delete(username: str) -> int:
    handle = _web_handle(username)
    async with async_session_factory() as db:
        user = await _get_by_handle(db, handle)
        if user is None:
            print(f"error: user '{username}' not found", file=sys.stderr)
            return 1

        await db.execute(delete(User).where(User.id == user.id))  # type: ignore[arg-type]
        await db.commit()

    print(f"Deleted user {username}.")
    return 0


async def _get_by_handle(db: AsyncSession, handle: str) -> User | None:
    result = await db.execute(select(User).where(User.handle == handle))  # type: ignore[arg-type]
    return result.scalar_one_or_none()


# ─── argparse dispatcher ────────────────────────────────


def run_user_command(args: list[str]) -> int:
    """Entrypoint called by cli.main when argv[1] == 'user'.

    Returns a process exit code.
    """
    if not args:
        _print_user_help()
        return 2

    cmd, rest = args[0], args[1:]

    async def _runner() -> int:
        try:
            if cmd == "create":
                if len(rest) != 1:
                    _print_user_help()
                    return 2
                return await _create(rest[0])
            if cmd == "list":
                return await _list()
            if cmd == "reset-password":
                if len(rest) != 1:
                    _print_user_help()
                    return 2
                return await _reset_password(rest[0])
            if cmd == "delete":
                if len(rest) != 1:
                    _print_user_help()
                    return 2
                return await _delete(rest[0])
            _print_user_help()
            return 2
        finally:
            await engine.dispose()

    return asyncio.run(_runner())


def _print_user_help() -> None:
    print(
        "usage: berry-cli user <command> [args]\n"
        "\n"
        "Commands:\n"
        "  create <username>          Create a web user, print generated password\n"
        "  list                       List all web:* users\n"
        "  reset-password <username>  Reset password, force logout\n"
        "  delete <username>          Delete user (cascades to sessions / projects)\n",
        file=sys.stderr,
    )
