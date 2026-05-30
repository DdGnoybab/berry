"""Unit tests for ``search.yaml`` loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from berry.core.tools.web.config import SearchConfigError, load_search_config


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "search.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_substitutes_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_KEY", "tvly-real-secret")
    path = _write(
        tmp_path,
        """
        version: 1
        default: tavily
        providers:
          tavily:
            type: tavily
            api_key: ${MY_KEY}
            timeout_s: 10
        """,
    )
    cfg = load_search_config(path)
    assert cfg.providers["tavily"].api_key == "tvly-real-secret"
    assert cfg.providers["tavily"].timeout_s == 10
    assert cfg.default == "tavily"


def test_load_rejects_plaintext_api_key(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        version: 1
        default: tavily
        providers:
          tavily:
            type: tavily
            api_key: tvly-this-is-plaintext-bad
        """,
    )
    with pytest.raises(SearchConfigError, match=r"\$\{VAR\} placeholder"):
        load_search_config(path)


def test_load_raises_when_env_var_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEFINITELY_NOT_SET_TVLY", raising=False)
    path = _write(
        tmp_path,
        """
        version: 1
        default: tavily
        providers:
          tavily:
            type: tavily
            api_key: ${DEFINITELY_NOT_SET_TVLY}
        """,
    )
    with pytest.raises(SearchConfigError, match="not set"):
        load_search_config(path)


def test_load_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SearchConfigError, match="not found"):
        load_search_config(tmp_path / "nope.yaml")


def test_load_handles_provider_without_api_key(
    tmp_path: Path,
) -> None:
    """A future self-hosted provider may legitimately have no api_key."""
    path = _write(
        tmp_path,
        """
        version: 1
        default: searxng
        providers:
          searxng:
            type: searxng
            base_url: http://localhost:8080
        """,
    )
    cfg = load_search_config(path)
    assert cfg.providers["searxng"].api_key is None
