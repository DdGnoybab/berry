"""Berry 领域异常基类。

所有自定义异常都继承 BerryError,便于统一 catch / 日志 / 错误响应。
"""


class BerryError(Exception):
    """所有 Berry 自定义异常的基类。"""


class FileScopeError(BerryError):
    """A file path operation tried to escape the workspace root.

    Raised by berry.core.tools.files.path_scope when an LLM-supplied path
    resolves outside ``ToolContext.cwd``. The runtime catches this and turns
    it into a ToolResultBlock(is_error=True) so the LLM can self-correct.
    """
