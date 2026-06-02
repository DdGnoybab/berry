"""SystemPromptBuilder — assemble the learning assistant's system prompt.

Mirrors claw-code's `SystemPromptBuilder` (reference/claw-code_1/rust/crates/runtime/src/prompt.rs)
1:1 in structure, just Python-flavored.

Section order is fixed (matches the spec):

  static:
    1. Intro (with or without output style)
    2. Output Style                    (only if with_output_style was called)
    3. # System
    4. # Learning together
    5. # Executing actions with care
       __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__       ← cache split

  dynamic:
    6. # Environment context           (always)
    7. # Learning project context      (only if with_project_context)
    8. # Berry instructions            (only if instruction_files non-empty)
    9. # Runtime config                (only if with_runtime_config)
   10. ...append_sections              (any number, in call order)

The static prefix is byte-stable across sessions and benefits from Anthropic
prompt caching. Mutating sections.py invalidates the cache for everyone — see
the spec for cache-friendliness rationale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Self

from berry.assistants.learning.prompts.instruction_files import (
    discover_instruction_files,
    render_instruction_files,
)
from berry.assistants.learning.prompts.project_context import (
    ProjectContext,
    discover_project_context,
    render_project_context,
)
from berry.assistants.learning.prompts.sections import (
    EXECUTING_ACTIONS,
    LEARNING_TOGETHER,
    SYSTEM,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    intro,
)


class ModelFamilyIdentity(Enum):
    """Identity label rendered into Environment context.

    Generic = "an AI assistant" — useful when running with non-Claude models so
    we don't fight a provider's own self-identity prompt.
    """

    CLAUDE = "claude"
    GENERIC = "generic"

    def family_label(self) -> str:
        return _FAMILY_LABELS[self]


_FAMILY_LABELS: dict[ModelFamilyIdentity, str] = {
    ModelFamilyIdentity.CLAUDE: "Claude Opus 4.6",
    ModelFamilyIdentity.GENERIC: "an AI assistant",
}


@dataclass
class SystemPromptBuilder:
    """Method-chained builder for the system prompt sections list."""

    _output_style: tuple[str, str] | None = None
    _os: tuple[str, str] | None = None
    _model_family: ModelFamilyIdentity = ModelFamilyIdentity.CLAUDE
    _project_context: ProjectContext | None = None
    _runtime_config: dict[str, Any] | None = None
    _berry_version: str | None = None
    _berry_source_path: str | None = None
    _appended: list[str] = field(default_factory=list)

    def with_output_style(self, name: str, prompt: str) -> Self:
        self._output_style = (name, prompt)
        return self

    def with_os(self, os_name: str, os_version: str) -> Self:
        self._os = (os_name, os_version)
        return self

    def with_model_family(self, identity: ModelFamilyIdentity) -> Self:
        self._model_family = identity
        return self

    def with_project_context(self, ctx: ProjectContext) -> Self:
        self._project_context = ctx
        return self

    def with_runtime_config(self, config: dict[str, Any]) -> Self:
        self._runtime_config = config
        return self

    def with_berry_version(self, version: str) -> Self:
        self._berry_version = version
        return self

    def with_berry_source_path(self, source_path: str) -> Self:
        """Absolute path to the berry source repo, e.g. /Users/alex/code/berry.

        Rendered into Environment context so the LLM can build the exact
        ``uv run --project <path> python -m berry.entrypoints.cli`` command
        when telling the user how to switch workspaces (Topic-mismatch flow).
        """
        self._berry_source_path = source_path
        return self

    def append_section(self, section: str) -> Self:
        self._appended.append(section)
        return self

    def build(self) -> list[str]:
        sections: list[str] = []

        # 1. Intro (phrasing depends on whether output style is set)
        sections.append(intro(self._output_style is not None))

        # 2. Output Style (optional)
        if self._output_style is not None:
            name, body = self._output_style
            sections.append(f"# Output Style: {name}\n{body}")

        # 3-5. Static system / discipline / actions
        sections.append(SYSTEM)
        sections.append(LEARNING_TOGETHER)
        sections.append(EXECUTING_ACTIONS)

        # Boundary (marks end of static prefix for prompt cache analysis)
        sections.append(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)

        # 6. Environment context (always)
        sections.append(self._render_environment())

        # 7. Learning project context (optional)
        if self._project_context is not None:
            sections.append(render_project_context(self._project_context))

            # 8. Berry instructions (optional, requires project context)
            if self._project_context.instruction_files:
                rendered = render_instruction_files(
                    self._project_context.instruction_files,
                )
                if rendered:
                    sections.append(rendered)

        # 9. Runtime config (optional)
        if self._runtime_config is not None:
            sections.append(self._render_runtime_config())

        # 10. Appended sections (subagent role descriptions, etc.)
        sections.extend(self._appended)

        return sections

    def render(self) -> str:
        return "\n\n".join(self.build())

    # ─── private renderers ────────────────────────────────────────────────

    def _render_environment(self) -> str:
        cwd = (
            str(self._project_context.cwd)
            if self._project_context is not None
            else "unknown"
        )
        date = (
            self._project_context.current_date
            if self._project_context is not None
            else "unknown"
        )
        os_name, os_version = self._os if self._os is not None else ("unknown", "unknown")
        version = self._berry_version if self._berry_version else "unknown"
        source_path = self._berry_source_path if self._berry_source_path else "unknown"

        bullets = [
            f" - Model family: {self._model_family.family_label()}",
            f" - Working directory: {cwd}",
            f" - Date: {date}",
            f" - Platform: {os_name} {os_version}",
            f" - Berry version: {version}",
            f" - Berry source path: {source_path}",
        ]
        return "\n".join(["# Environment context", *bullets])

    def _render_runtime_config(self) -> str:
        config = self._runtime_config or {}
        # Pretty-printed JSON dump so the LLM sees structure clearly.
        body = json.dumps(config, ensure_ascii=False, indent=2, sort_keys=False)
        return f"# Runtime config\n{body}"


def load_system_prompt(
    *,
    cwd: Path,
    current_date: str,
    os_name: str,
    os_version: str,
    model_family: ModelFamilyIdentity,
    settings: dict[str, Any],
    berry_version: str,
    berry_source_path: str | None = None,
) -> list[str]:
    """One-shot assembly: discover environment + build prompt sections.

    GoalTutor calls this once per session. Subsequent turns reuse the result —
    discovery is a snapshot, not refreshed mid-session (see spec § 7).
    """
    notes_dir = settings.get("notes_dir", "notes")

    project_context = discover_project_context(cwd, current_date, notes_dir)
    instruction_files = discover_instruction_files(cwd)

    # Pull instruction files into the project_context so build() can render the
    # # Berry instructions section in its proper slot.
    project_context = ProjectContext(
        cwd=project_context.cwd,
        current_date=project_context.current_date,
        notes_dir=project_context.notes_dir,
        notes_index=project_context.notes_index,
        instruction_files=instruction_files,
        progress=project_context.progress,
        quizzes_index=project_context.quizzes_index,
        references_index=project_context.references_index,
    )

    builder = (
        SystemPromptBuilder()
        .with_os(os_name, os_version)
        .with_model_family(model_family)
        .with_berry_version(berry_version)
        .with_project_context(project_context)
        .with_runtime_config(settings)
    )
    if berry_source_path is not None:
        builder = builder.with_berry_source_path(berry_source_path)
    return builder.build()


__all__ = [
    "ModelFamilyIdentity",
    "SystemPromptBuilder",
    "load_system_prompt",
]
