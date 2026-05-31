from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        default=Path("data"),
        description=(
            "本地数据目录的根。Workspace 工具(Round 3 起)会在这下面写 .md。"
            "Goal 的 workspace_path 都是相对此目录的相对路径。"
        ),
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
    allowed_open_ids: list[str] = Field(default_factory=list)

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
