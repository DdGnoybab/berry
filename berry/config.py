from pathlib import Path

from pydantic import Field
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


settings = Settings()  # type: ignore[call-arg]
