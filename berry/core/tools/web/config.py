"""search.yaml loader with ${VAR} env-substitution + plaintext-key guard.

Mirrors ``berry/core/llm/config.py`` so the operational pattern is the same
across web search and LLM configs (1) every secret is referenced via ``${VAR}``,
(2) the YAML is allowed in git, real values stay in ``.env``, (3) plaintext
keys in YAML are rejected at load time.

We intentionally don't share a util module with ``llm/config.py`` — the
reuse cost (one helper file) outweighs the duplication of ~30 lines. Keep
the two configs evolvable independently.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from berry.domain.errors import BerryError

_ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class SearchConfigError(BerryError):
    """yaml parse / validation / env substitution failures."""


class ProviderConfig(BaseModel):
    """One provider entry from ``providers:`` in search.yaml."""

    type: str
    api_key: str | None = None
    base_url: str | None = None
    timeout_s: float = 15.0
    extra: dict[str, Any] = Field(default_factory=dict)


class SearchConfig(BaseModel):
    """search.yaml top-level shape."""

    version: int
    default: str
    providers: dict[str, ProviderConfig]


def _substitute_env(value: Any) -> Any:
    """Recursively replace ${VAR} in strings/lists/dicts. Raises if a
    referenced env var is missing.
    """
    if isinstance(value, str):

        def _replace(m: re.Match[str]) -> str:
            var = m.group(1)
            if var not in os.environ:
                raise SearchConfigError(
                    f"env var {var!r} referenced in search.yaml is not set"
                )
            return os.environ[var]

        return _ENV_PLACEHOLDER_RE.sub(_replace, value)
    if isinstance(value, dict):
        return {k: _substitute_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v) for v in value]
    return value


def _check_no_plaintext_keys(raw_providers: dict[str, dict[str, Any]]) -> None:
    """Every ``api_key`` that's present must be a ${VAR} placeholder."""
    for name, provider in raw_providers.items():
        api_key = provider.get("api_key")
        if api_key is None:
            continue
        if not isinstance(api_key, str):
            raise SearchConfigError(
                f"search.yaml: provider {name!r} api_key must be a string"
            )
        if not _ENV_PLACEHOLDER_RE.fullmatch(api_key.strip()):
            raise SearchConfigError(
                f"search.yaml: provider {name!r} api_key must use "
                f"${{VAR}} placeholder, not plaintext"
            )


def load_search_config(path: Path) -> SearchConfig:
    """Read + validate + env-substitute. Raises SearchConfigError on any failure."""
    if not path.exists():
        raise SearchConfigError(f"search config file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise SearchConfigError(f"yaml parse error: {exc}") from exc

    if not isinstance(raw, dict):
        raise SearchConfigError("search.yaml top-level must be a mapping")

    raw_providers = raw.get("providers", {})
    if not isinstance(raw_providers, dict):
        raise SearchConfigError("search.yaml: 'providers' must be a mapping")

    _check_no_plaintext_keys(raw_providers)
    substituted = _substitute_env(raw)

    try:
        return SearchConfig.model_validate(substituted)
    except Exception as exc:
        raise SearchConfigError(f"search.yaml schema validation failed: {exc}") from exc
