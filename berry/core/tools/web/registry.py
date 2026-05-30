"""SearchProviderRegistry — load search.yaml, instantiate providers by ``type``.

Mirrors ``core/llm/registry.ModelRegistry`` in shape: ``load()`` from yaml,
``get(name)`` returns a provider, ``default()`` returns the configured default.
Day-1 only knows about ``tavily``; new types register here as adapters land.
"""

from __future__ import annotations

from pathlib import Path

from berry.core.tools.web.base import SearchProvider
from berry.core.tools.web.config import (
    ProviderConfig,
    SearchConfig,
    SearchConfigError,
    load_search_config,
)
from berry.core.tools.web.providers.tavily import TavilyProvider


class SearchProviderRegistry:
    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path
        self._snapshot: SearchConfig | None = None
        self._instances: dict[str, SearchProvider] = {}

    def load(self) -> None:
        self._snapshot = load_search_config(self._config_path)
        # Eagerly instantiate every provider — fails early if api_key is wrong.
        self._instances = {
            name: _build_provider(name, cfg)
            for name, cfg in self._snapshot.providers.items()
        }

    def _require_loaded(self) -> SearchConfig:
        if self._snapshot is None:
            raise RuntimeError(
                "SearchProviderRegistry.load() must be called before use"
            )
        return self._snapshot

    def get(self, name: str) -> SearchProvider:
        self._require_loaded()
        if name not in self._instances:
            raise SearchConfigError(
                f"search provider {name!r} not registered "
                f"(available: {sorted(self._instances)})"
            )
        return self._instances[name]

    def default(self) -> SearchProvider:
        snap = self._require_loaded()
        return self.get(snap.default)


def _build_provider(name: str, cfg: ProviderConfig) -> SearchProvider:
    """Map ``cfg.type`` → concrete provider instance. Add new branches here
    when new SearchProvider implementations land.
    """
    if cfg.type == "tavily":
        if cfg.api_key is None:
            raise SearchConfigError(
                f"provider {name!r} (tavily) requires api_key"
            )
        return TavilyProvider(api_key=cfg.api_key, timeout_s=cfg.timeout_s)

    raise SearchConfigError(
        f"unknown provider type {cfg.type!r} for {name!r}"
    )
