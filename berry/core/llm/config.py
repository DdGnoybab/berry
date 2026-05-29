"""ModelEntry 数据模型 + yaml 加载 + ${ENV} 占位符替换。

设计要点:
- yaml 里 api_key 必须是 ${VAR} 形式,明文报错(防泄密)
- ${VAR} 在解析时从 os.environ 替换;env 没设视为配置错误
- 解析后 ModelEntry 内存中是真值,但 __repr__ 隐藏 api_key
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from berry.core.llm.enums import KnownApi, ModelKind
from berry.core.llm.errors import LlmConfigError

_ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class ModelDefaults(BaseModel):
    """yaml 里可选的请求默认参数。请求时 override。"""

    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None


class ModelEntry(BaseModel):
    """运行时 ModelRegistry 内的单条 model 记录。"""

    id: str
    kind: ModelKind
    api: KnownApi
    provider: str
    base_url: str
    model_name: str
    api_key: str                       # 已替换为真值(内存中)
    timeout_s: float = 60.0
    capabilities: list[str] = Field(default_factory=list)
    defaults: ModelDefaults = Field(default_factory=ModelDefaults)

    def __repr__(self) -> str:
        # 防止意外打印泄露 key
        return (
            f"ModelEntry(id={self.id!r}, kind={self.kind!r}, api={self.api!r}, "
            f"provider={self.provider!r}, model_name={self.model_name!r}, "
            f"api_key='[REDACTED]')"
        )


class ModelsConfig(BaseModel):
    """yaml 整体 schema。"""

    version: int
    models: list[ModelEntry]
    aliases: dict[str, str] = Field(default_factory=dict)
    fallback: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("models")
    @classmethod
    def _check_unique_ids(cls, v: list[ModelEntry]) -> list[ModelEntry]:
        ids = [m.id for m in v]
        dups = {x for x in ids if ids.count(x) > 1}
        if dups:
            raise ValueError(f"duplicate model ids: {sorted(dups)}")
        return v


def _substitute_env(value: Any) -> Any:
    """递归替换 dict / list / str 里的 ${VAR}。

    Raises:
        LlmConfigError: 占位符引用的 env 未设置。
    """
    if isinstance(value, str):
        def _replace(m: re.Match[str]) -> str:
            var = m.group(1)
            if var not in os.environ:
                raise LlmConfigError(
                    f"env var {var!r} referenced in models.yaml is not set"
                )
            return os.environ[var]

        return _ENV_PLACEHOLDER_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    return value


def _check_no_plaintext_keys(raw_models: list[dict[str, Any]]) -> None:
    """yaml 原始内容里 api_key 必须是 ${VAR} 形式,禁止明文。"""
    for m in raw_models:
        key = m.get("api_key", "")
        if not isinstance(key, str):
            raise LlmConfigError(
                f"models.yaml: model {m.get('id')!r} api_key must be string"
            )
        if not _ENV_PLACEHOLDER_RE.fullmatch(key.strip()):
            raise LlmConfigError(
                f"models.yaml: model {m.get('id')!r} api_key must use "
                f"${{VAR}} placeholder, not plaintext"
            )


def load_models_config(path: Path) -> ModelsConfig:
    """从 yaml 文件加载并解析配置。

    Raises:
        LlmConfigError: 文件不存在 / yaml 格式错 / 明文 key / env 缺失 / schema 不合法。
    """
    if not path.exists():
        raise LlmConfigError(f"models config file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise LlmConfigError(f"yaml parse error: {exc}") from exc

    if not isinstance(raw, dict):
        raise LlmConfigError("models.yaml top-level must be a mapping")

    raw_models = raw.get("models", [])
    if not isinstance(raw_models, list):
        raise LlmConfigError("models.yaml: 'models' must be a list")

    # 1. 先校验 yaml 原始内容的 api_key 是占位符形式(防明文)
    _check_no_plaintext_keys(raw_models)

    # 2. 替换 ${ENV}
    substituted = _substitute_env(raw)

    # 3. Pydantic 校验
    try:
        return ModelsConfig.model_validate(substituted)
    except Exception as exc:
        raise LlmConfigError(f"models.yaml schema validation failed: {exc}") from exc
