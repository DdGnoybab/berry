"""structlog 配置。

用法:
    from berry.observability.logging import get_logger
    logger = get_logger(__name__)
    logger.info("user_login", user_id="...", channel="feishu")

设计原则(对应 CLAUDE.md §5 日志):
- 业务代码绝不 print
- 必须带 context kwargs,不要拼字符串
- 生产 JSON 输出,本地 console 可读(LOG_FORMAT=console)
- 敏感字段不落日志
"""

import logging
import sys

import structlog
from structlog.types import Processor

from berry.config import settings


def configure_logging(level: str | None = None, log_format: str = "json") -> None:
    """初始化全局日志配置。在进程启动时调用一次。

    Args:
        level: 日志级别(DEBUG/INFO/WARNING/ERROR)。None 时取 settings.log_level
        log_format: "json"(生产)或 "console"(本地易读)
    """
    actual_level = (level or settings.log_level).upper()

    # ─── stdlib logging 也走 structlog ───
    # uvicorn / asyncpg / sqlalchemy 都用 stdlib logging,统一格式
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=actual_level,
    )

    # ─── structlog processor 链 ───
    # 链式处理:每条日志依次过这些 processor,最后输出
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,         # 注入 contextvars(request_id 等)
        structlog.processors.add_log_level,              # 加 level 字段
        structlog.processors.TimeStamper(fmt="iso", utc=True),  # ISO 时间戳
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "console":
        # 本地开发:彩色 + 易读
        renderer: Processor = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # 生产:JSON,便于日志聚合
        shared_processors.append(structlog.processors.format_exc_info)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[actual_level]
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取 logger。

    用法:
        logger = get_logger(__name__)
        logger.info("event_name", key1=val1, key2=val2)
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
