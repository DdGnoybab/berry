"""Method registry / channel 共享的错误码.

业务错误统一抛 ProtocolError, transport 层包成各自格式(HTTP RPC = 200 + error
body; SSE = event: error; CLI = 渲染错误).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    METHOD_NOT_FOUND = "METHOD_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"

    USER_NOT_FOUND = "USER_NOT_FOUND"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PROJECT_NAME_CONFLICT = "PROJECT_NAME_CONFLICT"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    MATERIAL_NOT_FOUND = "MATERIAL_NOT_FOUND"
    UPLOAD_NOT_FOUND = "UPLOAD_NOT_FOUND"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"

    INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"

    APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"
    APPROVAL_NOT_FOUND = "APPROVAL_NOT_FOUND"

    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"

    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ProtocolError(Exception):
    """业务错误的统一基类.

    handler 抛它, registry 捕获后传播给 transport; transport 自己渲染.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
