"""Web channel auth module.

Components:
  - passwords.py  — bcrypt hash / verify
  - tokens.py     — random session token + sha256 helper
  - repo.py       — AuthSessionRepo: CRUD on auth_sessions table
  - middleware.py — FastAPI middleware: cookie → request.state.user_id
  - routes.py     — /auth/login / /auth/logout / /auth/me
  - deps.py       — require_admin: admin-only route dependency
"""

from berry.channels.web.auth.deps import AdminUser, require_admin
from berry.channels.web.auth.middleware import AuthMiddleware
from berry.channels.web.auth.routes import router as auth_router

__all__ = ["AdminUser", "AuthMiddleware", "auth_router", "require_admin"]
