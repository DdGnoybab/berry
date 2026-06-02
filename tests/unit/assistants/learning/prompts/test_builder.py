"""TDD tests for SystemPromptBuilder + load_system_prompt.

Verify section assembly order, conditional sections, and the static/dynamic
boundary marker placement. The exact text of each static segment lives in
sections.py and has its own assertions in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from berry.assistants.learning.prompts.builder import (
    ModelFamilyIdentity,
    SystemPromptBuilder,
    load_system_prompt,
)
from berry.assistants.learning.prompts.instruction_files import ContextFile
from berry.assistants.learning.prompts.project_context import (
    NoteEntry,
    ProjectContext,
)
from berry.assistants.learning.prompts.sections import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
)


# ─── builder section ordering ─────────────────────────────────────────────


def test_minimal_build_has_six_static_sections_then_boundary(tmp_path: Path) -> None:
    """Bare builder still emits intro + System + Learning together + Executing
    + boundary + Environment context."""
    sections = SystemPromptBuilder().build()

    # Static prefix:
    assert sections[0].startswith("You are Berry,")
    assert sections[1].startswith("# System")
    assert sections[2].startswith("# Learning together")
    assert sections[3].startswith("# Executing actions with care")
    assert sections[4] == SYSTEM_PROMPT_DYNAMIC_BOUNDARY
    # Environment is always pushed (cwd/date may be 'unknown' but section exists).
    assert sections[5].startswith("# Environment context")


def test_environment_uses_unknown_when_no_project_context() -> None:
    """No project context → Environment section still renders with 'unknown' fallbacks."""
    rendered = SystemPromptBuilder().render()

    assert "Working directory: unknown" in rendered
    assert "Date: unknown" in rendered


def test_with_project_context_pushes_learning_project_context(tmp_path: Path) -> None:
    """When project context is provided, # Learning project context section appears."""
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=[],
    )
    out = SystemPromptBuilder().with_project_context(ctx).render()

    assert "# Learning project context" in out
    assert "Today's date is 2026-05-31." in out


def test_environment_uses_project_context_cwd_and_date(tmp_path: Path) -> None:
    """When project context is provided, Environment cwd/date come from it."""
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=[],
    )
    out = SystemPromptBuilder().with_project_context(ctx).render()

    assert f"Working directory: {tmp_path}" in out
    assert "Date: 2026-05-31" in out


def test_with_instruction_files_pushes_berry_instructions_section(
    tmp_path: Path,
) -> None:
    """When project_context.instruction_files is non-empty, the section appears."""
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=[],
        instruction_files=[
            ContextFile(path=tmp_path / "BERRY.md", content="rule one"),
        ],
    )
    out = SystemPromptBuilder().with_project_context(ctx).render()

    assert "# Berry instructions" in out
    assert "rule one" in out


def test_no_instruction_files_omits_berry_instructions_section(tmp_path: Path) -> None:
    """Empty instruction_files list → no '# Berry instructions' section."""
    ctx = ProjectContext(
        cwd=tmp_path,
        current_date="2026-05-31",
        notes_dir="notes",
        notes_index=[],
        instruction_files=[],
    )
    out = SystemPromptBuilder().with_project_context(ctx).render()
    assert "# Berry instructions" not in out


def test_with_runtime_config_pushes_runtime_config_section() -> None:
    """Calling with_runtime_config emits '# Runtime config' with JSON dump."""
    out = SystemPromptBuilder().with_runtime_config(
        {"language": "zh-CN", "notes_dir": "notes"},
    ).render()

    assert "# Runtime config" in out
    assert '"language": "zh-CN"' in out
    assert '"notes_dir": "notes"' in out


def test_runtime_config_section_omitted_when_not_provided() -> None:
    """No runtime config → no '# Runtime config' section."""
    out = SystemPromptBuilder().render()
    assert "# Runtime config" not in out


def test_append_section_pushes_to_end_of_build() -> None:
    """append_section adds raw strings to the tail."""
    sections = SystemPromptBuilder().append_section("Custom subagent rule.").build()
    assert sections[-1] == "Custom subagent rule."


def test_with_os_renders_platform_line() -> None:
    """with_os populates the Platform: line in Environment section."""
    out = SystemPromptBuilder().with_os("darwin", "25.5.0").render()
    assert "Platform: darwin 25.5.0" in out


def test_with_berry_source_path_renders_path_line() -> None:
    """with_berry_source_path adds 'Berry source path: ...' to Environment.

    LLM uses this when telling the user how to restart the REPL after
    creating a new topic workspace (Topic-mismatch handling in section 4).
    """
    out = (
        SystemPromptBuilder()
        .with_berry_source_path("/Users/alex/code/berry")
        .render()
    )
    assert "Berry source path: /Users/alex/code/berry" in out


def test_with_berry_version_renders_version_line() -> None:
    """with_berry_version adds 'Berry version: ...' to Environment."""
    out = SystemPromptBuilder().with_berry_version("0.0.3").render()
    assert "Berry version: 0.0.3" in out


def test_model_family_default_is_claude_label() -> None:
    """Default identity → 'Claude Opus 4.6' label."""
    out = SystemPromptBuilder().render()
    assert "Model family: Claude Opus 4.6" in out


def test_model_family_generic_label() -> None:
    """Generic identity → 'an AI assistant' label."""
    out = (
        SystemPromptBuilder()
        .with_model_family(ModelFamilyIdentity.GENERIC)
        .render()
    )
    assert "Model family: an AI assistant" in out


def test_render_joins_sections_with_double_newline() -> None:
    """render() = '\\n\\n'.join(build())."""
    builder = SystemPromptBuilder()
    sections = builder.build()
    assert builder.render() == "\n\n".join(sections)


def test_with_output_style_inserts_section_and_changes_intro() -> None:
    """When output style set, intro phrasing changes and # Output Style section appears."""
    out = (
        SystemPromptBuilder()
        .with_output_style("Concise", "Prefer short answers.")
        .render()
    )
    assert "according to your \"Output Style\" below" in out
    assert "# Output Style: Concise" in out
    assert "Prefer short answers." in out


# ─── load_system_prompt entry point ────────────────────────────────────────


def test_load_system_prompt_returns_list_of_strings(tmp_path: Path) -> None:
    """The entry point returns a list[str] suitable for join('\\n\\n')."""
    sections = load_system_prompt(
        cwd=tmp_path,
        current_date="2026-05-31",
        os_name="darwin",
        os_version="25.5.0",
        model_family=ModelFamilyIdentity.CLAUDE,
        settings={"language": "zh-CN", "notes_dir": "notes"},
        berry_version="0.0.3",
    )

    assert isinstance(sections, list)
    assert all(isinstance(s, str) for s in sections)


def test_load_system_prompt_includes_environment_and_runtime_config(
    tmp_path: Path,
) -> None:
    """load_system_prompt produces the expected high-level pieces in one shot."""
    rendered = "\n\n".join(
        load_system_prompt(
            cwd=tmp_path,
            current_date="2026-05-31",
            os_name="darwin",
            os_version="25.5.0",
            model_family=ModelFamilyIdentity.CLAUDE,
            settings={"language": "zh-CN", "notes_dir": "notes"},
            berry_version="0.0.3",
        )
    )

    assert "You are Berry," in rendered
    assert SYSTEM_PROMPT_DYNAMIC_BOUNDARY in rendered
    assert "# Environment context" in rendered
    assert "# Learning project context" in rendered
    assert "# Runtime config" in rendered
    assert "Berry version: 0.0.3" in rendered


def test_load_system_prompt_discovers_berry_md(tmp_path: Path) -> None:
    """Entry point discovers BERRY.md files automatically."""
    (tmp_path / "BERRY.md").write_text("Custom rule for this project.")

    rendered = "\n\n".join(
        load_system_prompt(
            cwd=tmp_path,
            current_date="2026-05-31",
            os_name="darwin",
            os_version="25.5.0",
            model_family=ModelFamilyIdentity.CLAUDE,
            settings={"notes_dir": "notes"},
            berry_version="0.0.3",
        )
    )

    assert "# Berry instructions" in rendered
    assert "Custom rule for this project." in rendered


def test_load_system_prompt_preserves_progress_quizzes_references(tmp_path: Path) -> None:
    """load_system_prompt re-builds ProjectContext after instruction discovery.

    That re-build must NOT drop progress / quizzes_index / references_index
    that discover_project_context computed. (Regression: original load_*
    only copied notes_index + instruction_files into the new context.)
    """
    # Set up a project with PROGRESS.md + quizzes/ + references/
    (tmp_path / "PROGRESS.md").write_text(
        "> 最终目标: x\n\n### [in_progress] 1. m\n- 完成判据: c\n"
    )
    (tmp_path / "quizzes").mkdir()
    (tmp_path / "quizzes" / "m1.1-q1.md").write_text("# Q")
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "ref.md").write_text("# Ref")

    rendered = "\n\n".join(
        load_system_prompt(
            cwd=tmp_path,
            current_date="2026-06-01",
            os_name="darwin",
            os_version="25.5.0",
            model_family=ModelFamilyIdentity.CLAUDE,
            settings={"notes_dir": "notes"},
            berry_version="0.0.3",
        )
    )

    # All three derived blocks must appear.
    assert "Progress (from PROGRESS.md)" in rendered
    assert "Quizzes:" in rendered
    assert "References:" in rendered


def test_load_system_prompt_renders_berry_source_path_when_provided(
    tmp_path: Path,
) -> None:
    rendered = "\n\n".join(
        load_system_prompt(
            cwd=tmp_path,
            current_date="2026-06-01",
            os_name="darwin",
            os_version="25.5.0",
            model_family=ModelFamilyIdentity.CLAUDE,
            settings={"notes_dir": "notes"},
            berry_version="0.0.3",
            berry_source_path="/path/to/berry",
        )
    )
    assert "Berry source path: /path/to/berry" in rendered


def test_load_system_prompt_uses_notes_dir_from_settings(tmp_path: Path) -> None:
    """Entry point reads notes_dir from settings dict, defaulting to 'notes'."""
    custom = tmp_path / "study"
    custom.mkdir()
    (custom / "x.md").write_text("hi")

    rendered = "\n\n".join(
        load_system_prompt(
            cwd=tmp_path,
            current_date="2026-05-31",
            os_name="darwin",
            os_version="25.5.0",
            model_family=ModelFamilyIdentity.CLAUDE,
            settings={"notes_dir": "study"},
            berry_version="0.0.3",
        )
    )

    assert "study/x.md" in rendered
