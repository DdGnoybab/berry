"""Python 层枚举,代替 DB CHECK 约束。

写入时用 enum,读出时不强制 —— 老数据有奇怪值不会让查询炸。
"""

from enum import StrEnum


class SessionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SYSTEM = "system"


class Channel(StrEnum):
    FEISHU = "feishu"
    CLI = "cli"
