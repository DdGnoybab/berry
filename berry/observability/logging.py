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

输出 sink:
- stdout(永远):Docker json driver 接走,部署后 docker compose logs 可见
- 文件(可选,settings.log_to_file):写到 settings.log_dir/berry.log,
  每天 UTC 0 点滚转,旧文件 gzip,保留 settings.log_retention_days 天。
  这一份是 /admin/logs 面板的数据来源。
"""

import gzip
import logging
import logging.handlers
import shutil
import sys
from pathlib import Path

import structlog
from structlog.types import Processor

from berry.config import settings


def _gzip_rotator(source: str, dest: str) -> None:
    """轮转 hook:把刚切下来的文件压成 .gz 并删原文件。

    TimedRotatingFileHandler 默认会把昨天的文件改名为
    `berry.log.2026-06-12`,我们再叠一层 gzip → `berry.log.2026-06-12.gz`。
    """
    with open(source, "rb") as src, gzip.open(dest, "wb") as dst:
        shutil.copyfileobj(src, dst)
    Path(source).unlink()


def _add_file_sink(log_dir: Path, retention_days: int) -> None:
    """挂一个按天滚转 + gzip + 自动清理的文件 handler 到 root logger。

    backupCount=retention_days 会让 stdlib 自动删掉超期的备份 —
    不需要 cron / systemd timer。
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_dir / "berry.log"),
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
        utc=True,
    )
    handler.suffix = "%Y-%m-%d"
    handler.namer = lambda name: name + ".gz"
    handler.rotator = _gzip_rotator
    # structlog 已经把 record 渲染成了 JSON 字符串(processor 链最后一个),
    # 这里 stdlib formatter 只透传 message。
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)


def configure_logging(level: str | None = None, log_format: str = "json") -> None:
    """初始化全局日志配置。在进程启动时调用一次。

    Args:
        level: 日志级别(DEBUG/INFO/WARNING/ERROR)。None 时取 settings.log_level
        log_format: "json"(生产)或 "console"(本地易读)
    """
    actual_level = (level or settings.log_level).upper()

    # ─── stdlib logging ───
    # uvicorn / asyncpg / sqlalchemy 都用 stdlib logging,统一格式。
    # 用 force=True 是因为 uvicorn 自己也会调 basicConfig,我们要覆盖它。
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=actual_level,
        force=True,
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

    # 走 stdlib LoggerFactory(不再用 PrintLoggerFactory),这样
    # logging.getLogger() 上的所有 handler(stdout + 文件 sink)都收到日志。
    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[actual_level]
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ─── 文件 sink(可选)─────────────────────────────
    # 用 console renderer 时也照样落盘 JSON ?不:文件用什么格式取决于
    # processor 链最后一个 renderer。本地 dev 落盘的是 console 文本,
    # 生产落盘的是 JSON。/admin/logs 面板优先按 JSON 解析,解析失败回退
    # 显示原文 — 因此本地 dev 也能看,只是字段不会被解析成结构化。
    if settings.log_to_file:
        try:
            _add_file_sink(settings.log_dir, settings.log_retention_days)
        except OSError as e:
            # 启动期日志目录不可写不应该让进程起不来 — 打到 stdout 报警即可。
            sys.stderr.write(
                f"[logging] file sink disabled, log_dir={settings.log_dir}: {e}\n"
            )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取 logger。

    用法:
        logger = get_logger(__name__)
        logger.info("event_name", key1=val1, key2=val2)
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
