from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env at module import so any later `Settings()` call sees the values,
# regardless of which entrypoint imported berry.config first or what the
# user's current working directory is.
#
# We compute the path relative to *this* file: berry/config.py lives in
# <repo>/berry/, so `parent.parent` = <repo>/. The user can start a REPL
# from anywhere (e.g. /tmp/study-redis for dogfood) and still get the
# right .env.
_REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_REPO_ROOT / ".env")


class Settings(BaseSettings):
    """全局配置。从 .env 读。

    用法:
        from berry.config import settings
        url = settings.database_url
    """

    database_url: str = Field(
        ...,
        description="Postgres URL,无 driver 前缀。例:postgresql://user:pwd@host:5432/db",
    )
    log_level: str = "INFO"
    data_root: Path = Field(
        default_factory=lambda: _REPO_ROOT / "data",
        description=(
            "Berry 自家数据目录,默认 <repo_root>/data/(绝对路径,不会泄漏到用户 cwd)。"
            "Project 的 workspace_path 都是相对此目录的相对路径。"
            "学习场景下用户的 workspace 走 cwd,跟 data_root 无关。"
        ),
    )

    language: str = Field(
        default="zh-CN",
        description=(
            "Learning assistant 跟用户对话的默认语言。"
            "渲染进 system prompt 的 # Runtime config 段,LLM 据此决定回答语言。"
        ),
    )
    notes_dir: str = Field(
        default="notes",
        description=(
            "Learning project 笔记目录,相对 cwd。"
            "system prompt 段 7 (# Learning project context) 扫这里的 .md。"
        ),
    )

    cookie_secure: bool = Field(
        default=False,
        description=(
            "Web channel session cookie 是否仅 HTTPS。"
            "本地开发 / HTTP 部署 = False;生产 HTTPS = True。"
        ),
    )
    session_ttl_days: int = Field(
        default=7,
        description="Web 登录 cookie / auth_sessions 有效期(天)。",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def database_url_async(self) -> str:
        """asyncpg 用的 URL(应用代码 / SQLModel async session)。"""
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    @property
    def database_url_sync(self) -> str:
        """同步驱动用的 URL(alembic 用)。

        alembic 用同步 psycopg 跑迁移最稳定。
        """
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


class FeishuSettings(BaseSettings):
    """飞书 channel 凭证, Stage 4 接入, 本 stage 只占位."""

    app_id: str = Field(default="", description="飞书 app id, 环境变量 FEISHU_APP_ID")
    app_secret: SecretStr = SecretStr("")
    verification_token: SecretStr = SecretStr("")
    encrypt_key: SecretStr | None = None
    domain: str = "https://open.feishu.cn"
    bot_name: str = "berry"
    dm_policy: Literal["open", "allowlist"] = Field(
        default="open",
        description=(
            "DM 准入策略,对齐 openclaw `dmPolicy`:"
            "`open`(默认)放行所有 DM;"
            "`allowlist` 只放行 `FEISHU_ALLOWED_OPEN_IDS` 里的 open_id。"
        ),
    )
    allowed_open_ids: list[str] = Field(
        default_factory=list,
        description=(
            "DM allowlist. 逗号分隔的飞书 open_id 列表(如 'ou_a,ou_b')。"
            "仅当 dm_policy='allowlist' 时生效;"
            "open 模式下此字段被忽略(可留空)。"
        ),
    )
    bot_open_id: str = Field(
        default="",
        description=(
            "Bot 自身 open_id,群聊 @ 检测必需。空 → 群聊整体禁用(DM 不受影响)。"
            "启动前用 lark 控制台 / API 查一次粘进 .env。"
            "对齐 openclaw `ResolvedFeishuAccount.botOpenId`,简化:不做启动期自动解析。"
        ),
    )
    group_allow_from: list[str] = Field(
        default_factory=list,
        description=(
            "群聊白名单 chat_id 列表(逗号分隔,如 'oc_a,oc_b')。"
            "只有列表内的 chat_id 才会触发群聊会话;空列表 → 群聊禁用。"
            "对齐 openclaw `groupAllowFrom`,简化:不做 per-group sender allowlist。"
        ),
    )

    @field_validator("allowed_open_ids", "group_allow_from", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        # pydantic-settings 默认 list 期望 JSON;允许 'ou_a,ou_b' 这种 csv 写法。
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def enabled(self) -> bool:
        """凭证齐全时才视为启用。"""
        return bool(self.app_id and self.app_secret.get_secret_value())

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FEISHU_",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
