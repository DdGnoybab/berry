"""Web channel auth module.

Components:
  - passwords.py  — bcrypt hash / verify
  - tokens.py     — random session token + sha256 helper
  - repo.py       — AuthSessionRepo: CRUD on auth_sessions table
  - middleware.py — FastAPI middleware: cookie → request.state.user_id
  - routes.py     — /auth/login / /auth/logout / /auth/me
"""

from berry.channels.web.auth.middleware import AuthMiddleware
from berry.channels.web.auth.routes import router as auth_router

__all__ = ["AuthMiddleware", "auth_router"]
