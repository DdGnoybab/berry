"""Berry 领域异常基类。

所有自定义异常都继承 BerryError,便于统一 catch / 日志 / 错误响应。
"""


class BerryError(Exception):
    """所有 Berry 自定义异常的基类。"""
