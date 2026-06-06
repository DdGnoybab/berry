"""Unit tests for SkillTool."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from berry.core.tools.base import ToolContext
from berry.core.tools.core.skill import (
    SkillTool,
    _list_available_skills,
    _parse_description,
    _resolve_skill_path,
    _strip_frontmatter,
)


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(
        session_id="test-session",
        user_id=uuid4(),
        db=None,
        data_root=cwd,
        cwd=cwd,
    )


# ─── _parse_description ──────────────────────────────────────────────────────


def test_parse_description_with_frontmatter() -> None:
    content = '---\nname: test\ndescription: "A test skill"\n---\n\n# Content'
    assert _parse_description(content) == "A test skill"


def test_parse_description_no_frontmatter() -> None:
    content = "# Just markdown\n\nNo frontmatter here."
    assert _parse_description(content) is None


def test_parse_description_single_quotes() -> None:
    content = "---\nname: x\ndescription: 'Single quoted'\n---\n\nbody"
    assert _parse_description(content) == "Single quoted"


# ─── _strip_frontmatter ──────────────────────────────────────────────────────


def test_strip_frontmatter_removes_header() -> None:
    content = "---\nname: test\n---\n\n# Body here"
    result = _strip_frontmatter(content)
    assert "# Body here" in result
    assert "---" not in result


def test_strip_frontmatter_no_header_returns_unchanged() -> None:
    content = "# Just content\nNo frontmatter."
    assert _strip_frontmatter(content) == content


# ─── _resolve_skill_path ─────────────────────────────────────────────────────


def test_resolve_skill_dir_with_skill_md(tmp_path: Path) -> None:
    """Finds <root>/<name>/SKILL.md pattern."""
    skills_dir = tmp_path / ".berry" / "skills" / "brainstorming"
    skills_dir.mkdir(parents=True)
    skill_file = skills_dir / "SKILL.md"
    skill_file.write_text("# Brainstorming\n\nThink first.")

    result = _resolve_skill_path("brainstorming", tmp_path)
    assert result == skill_file


def test_resolve_skill_direct_md(tmp_path: Path) -> None:
    """Finds <root>/<name>.md pattern."""
    skills_dir = tmp_path / ".berry" / "skills"
    skills_dir.mkdir(parents=True)
    skill_file = skills_dir / "quick-check.md"
    skill_file.write_text("# Quick Check\n\nDo a quick check.")

    result = _resolve_skill_path("quick-check", tmp_path)
    assert result == skill_file


def test_resolve_skill_not_found(tmp_path: Path) -> None:
    result = _resolve_skill_path("nonexistent", tmp_path)
    assert result is None


def test_resolve_skill_empty_name(tmp_path: Path) -> None:
    result = _resolve_skill_path("", tmp_path)
    assert result is None


def test_resolve_skill_strips_leading_slash(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".berry" / "skills" / "myskill"
    skills_dir.mkdir(parents=True)
    skill_file = skills_dir / "SKILL.md"
    skill_file.write_text("content")

    result = _resolve_skill_path("/myskill", tmp_path)
    assert result == skill_file


# ─── _list_available_skills ──────────────────────────────────────────────────


def test_list_available_skills(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".berry" / "skills"

    # Directory skill
    (skills_dir / "alpha").mkdir(parents=True)
    (skills_dir / "alpha" / "SKILL.md").write_text("alpha skill")

    # File skill
    (skills_dir / "beta.md").write_text("beta skill")

    # Directory without SKILL.md (should not appear)
    (skills_dir / "gamma").mkdir(parents=True)
    (skills_dir / "gamma" / "README.md").write_text("not a skill")

    available = _list_available_skills(tmp_path)
    assert "alpha" in available
    assert "beta" in available
    assert "gamma" not in available


def test_list_available_skills_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Sandbox HOME so the user's ~/.berry/skills/ doesn't bleed into test
    # results (e.g. when berry-feishu has been run, learning is installed there).
    monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))
    available = _list_available_skills(tmp_path)
    assert available == []


# ─── SkillTool.execute ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_loads_skill(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".berry" / "skills" / "tdd"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(
        '---\nname: tdd\ndescription: "Test driven development"\n---\n\n# TDD\n\nWrite tests first.'
    )

    tool = SkillTool()
    result = await tool.execute({"skill": "tdd"}, _ctx(tmp_path))

    assert "Skill: tdd" in result
    assert "Description: Test driven development" in result
    assert "# TDD" in result
    assert "Write tests first." in result


@pytest.mark.asyncio
async def test_execute_with_args(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".berry" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "research.md").write_text("# Research\n\nDo research on the topic.")

    tool = SkillTool()
    result = await tool.execute(
        {"skill": "research", "args": "quantum computing"},
        _ctx(tmp_path),
    )

    assert "Arguments: quantum computing" in result
    assert "# Research" in result


@pytest.mark.asyncio
async def test_execute_skill_not_found(tmp_path: Path) -> None:
    tool = SkillTool()
    result = await tool.execute({"skill": "nonexistent"}, _ctx(tmp_path))

    assert "Error: unknown skill: nonexistent" in result


@pytest.mark.asyncio
async def test_execute_empty_name(tmp_path: Path) -> None:
    tool = SkillTool()
    result = await tool.execute({"skill": ""}, _ctx(tmp_path))

    assert "Error: skill name must not be empty" in result
