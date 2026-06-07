"""Tests for init_workspace bootstrap."""

from __future__ import annotations

from pathlib import Path

from berry.skills.learning.init_workspace import (
    ensure_workspace_skeleton,
    init_learning_workspace,
    sync_skill_to_user_dir,
)


def test_sync_skill_to_user_dir_writes_skill_md(tmp_path: Path) -> None:
    target_dir = tmp_path / "skills" / "learning"
    written = sync_skill_to_user_dir(target_dir)
    assert written.is_file()
    content = written.read_text(encoding="utf-8")
    # Sanity: it's the actual SKILL.md, not a stub
    assert "Learning" in content
    assert "Iron Law" in content


def test_sync_skill_overwrites_existing(tmp_path: Path) -> None:
    target_dir = tmp_path / "skills" / "learning"
    target_dir.mkdir(parents=True)
    (target_dir / "SKILL.md").write_text("STALE", encoding="utf-8")
    sync_skill_to_user_dir(target_dir)
    assert (target_dir / "SKILL.md").read_text(encoding="utf-8") != "STALE"


def test_ensure_workspace_skeleton_creates_dirs_and_template(tmp_path: Path) -> None:
    ws = tmp_path / "redis"
    ensure_workspace_skeleton(ws)
    assert ws.is_dir()
    assert (ws / ".berry").is_dir()
    learner = ws / "LEARNER.md"
    assert learner.is_file()
    content = learner.read_text(encoding="utf-8")
    assert "Learner Profile" in content
    assert "## 背景" in content


def test_ensure_workspace_skeleton_does_not_overwrite_user_content(tmp_path: Path) -> None:
    ws = tmp_path / "redis"
    ws.mkdir()
    learner = ws / "LEARNER.md"
    learner.write_text("MY USER CONTENT", encoding="utf-8")
    ensure_workspace_skeleton(ws)
    # User content survived
    assert learner.read_text(encoding="utf-8") == "MY USER CONTENT"


def test_ensure_workspace_skeleton_idempotent(tmp_path: Path) -> None:
    ws = tmp_path / "redis"
    ensure_workspace_skeleton(ws)
    ensure_workspace_skeleton(ws)
    ensure_workspace_skeleton(ws)
    # Still good
    assert (ws / ".berry").is_dir()
    assert (ws / "LEARNER.md").is_file()


def test_init_learning_workspace_creates_skeleton(tmp_path: Path, monkeypatch) -> None:
    """init_learning_workspace also tries to write to ~/.berry/skills/learning/.
    We can't easily redirect that without touching home, so just verify the
    skeleton part is correct.
    """
    ws = tmp_path / "redis"
    monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))
    init_learning_workspace(ws)
    assert ws.is_dir()
    assert (ws / ".berry").is_dir()
    assert (ws / "LEARNER.md").is_file()
