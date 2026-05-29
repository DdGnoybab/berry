"""ModelRegistry —— 维护内存中的「当前模型快照」。

Batch 1 只实现 load() + get();reload / watch 留给 Batch 4。
"""

from pathlib import Path

from berry.llm.config import ModelEntry, ModelsConfig, load_models_config
from berry.llm.enums import ModelKind
from berry.llm.errors import LlmModelNotFoundError


class ModelRegistry:
    """模型 catalog 的内存快照 + 查询接口。"""

    def __init__(self, config_path: Path):
        self._config_path = config_path
        self._snapshot: ModelsConfig | None = None

    def load(self) -> None:
        """首次加载;失败抛异常(进程启动失败比静默用空配置好)。"""
        self._snapshot = load_models_config(self._config_path)

    def _require_snapshot(self) -> ModelsConfig:
        if self._snapshot is None:
            raise RuntimeError("ModelRegistry.load() must be called before use")
        return self._snapshot

    def get(self, model_id_or_alias: str) -> ModelEntry:
        """按 id 或 alias 查找 ModelEntry。

        Raises:
            LlmModelNotFoundError: 找不到。
        """
        snap = self._require_snapshot()

        # 先解析 alias
        real_id = snap.aliases.get(model_id_or_alias, model_id_or_alias)

        for m in snap.models:
            if m.id == real_id:
                return m

        raise LlmModelNotFoundError(
            f"model {model_id_or_alias!r} not found in catalog"
        )

    def list_models(self, kind: ModelKind | None = None) -> list[ModelEntry]:
        """列出所有 model(可按 kind 过滤)。"""
        snap = self._require_snapshot()
        if kind is None:
            return list(snap.models)
        return [m for m in snap.models if m.kind == kind]

    def get_fallback_chain(self, model_id: str) -> list[str]:
        """V1 用:返回 [primary, fallback1, ...];Batch 1 直接返回 [primary]。"""
        snap = self._require_snapshot()
        real_id = snap.aliases.get(model_id, model_id)
        return snap.fallback.get(real_id, [real_id])
