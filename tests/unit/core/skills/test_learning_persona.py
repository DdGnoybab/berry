"""Tests for the workspace-aware learning persona augmenter."""

from __future__ import annotations

from pathlib import Path

from berry.core.skills.learning_persona import (
    augment_system_prompt,
    is_learning_workspace,
)


def test_no_progress_json_returns_base(tmp_path: Path) -> None:
    base = "BASE_PROMPT"
    out = augment_system_prompt(base, tmp_path)
    assert out == base


def test_with_progress_json_appends_persona_and_bootstrap(tmp_path: Path) -> None:
    (tmp_path / ".berry").mkdir()
    (tmp_path / ".berry" / "progress.json").write_text("{}", encoding="utf-8")
    out = augment_system_prompt("BASE_PROMPT", tmp_path)
    assert out.startswith("BASE_PROMPT")
    assert "Learning Mode (ACTIVE)" in out
    assert 'skill="learning"' in out


def test_learner_md_inlined_when_present(tmp_path: Path) -> None:
    (tmp_path / ".berry").mkdir()
    (tmp_path / ".berry" / "progress.json").write_text("{}", encoding="utf-8")
    (tmp_path / "LEARNER.md").write_text("- topic: Redis\n- goal: interview", encoding="utf-8")
    out = augment_system_prompt("BASE", tmp_path)
    assert "Learner Profile" in out
    assert "topic: Redis" in out


def test_is_learning_workspace_predicate(tmp_path: Path) -> None:
    assert is_learning_workspace(tmp_path) is False
    (tmp_path / ".berry").mkdir()
    assert is_learning_workspace(tmp_path) is False
    (tmp_path / ".berry" / "progress.json").write_text("{}", encoding="utf-8")
    assert is_learning_workspace(tmp_path) is True


def test_idempotent_call(tmp_path: Path) -> None:
    (tmp_path / ".berry").mkdir()
    (tmp_path / ".berry" / "progress.json").write_text("{}", encoding="utf-8")
    a = augment_system_prompt("BASE", tmp_path)
    b = augment_system_prompt("BASE", tmp_path)
    assert a == b
