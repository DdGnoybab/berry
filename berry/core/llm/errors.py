"""LLM 错误家族。

Adapter 把各家 SDK 异常映射到这里,Gateway / 业务层不直接 catch SDK 异常。
"""

from berry.domain.errors import BerryError


class LlmError(BerryError):
    """LLM 相关错误基类。"""


class LlmConfigError(LlmError):
    """yaml 解析 / 校验失败 / env 占位符未替换。"""


class LlmModelNotFoundError(LlmError):
    """ModelRegistry 找不到指定 model_id 或 alias。"""


class LlmAdapterNotFoundError(LlmError):
    """对应协议没有 adapter 注册。"""


class LlmAuthError(LlmError):
    """401 / 403。一般是 key 错或权限不足,不应自动重试。"""


class LlmRateLimitError(LlmError):
    """429。可重试,但需要退避。"""


class LlmServerError(LlmError):
    """5xx。可重试。"""


class LlmTimeoutError(LlmError):
    """超时。"""


class LlmInvalidRequestError(LlmError):
    """400 / 请求格式错误。不应重试。"""


class LlmStreamError(LlmError):
    """流中断 / 数据格式错。"""
