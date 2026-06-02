"""Learning assistant prompt assembly.

Public surface:
- ``SystemPromptBuilder`` / ``ModelFamilyIdentity`` — fluent builder for tests.
- ``load_system_prompt`` — one-shot entry point used by GoalTutor.
- ``ProjectContext`` / ``NoteEntry`` / ``ContextFile`` — dataclasses surfaced
  so tests and tooling can construct fixtures without going through discovery.
- ``SYSTEM_PROMPT_DYNAMIC_BOUNDARY`` — re-exported for prompt-cache tooling.
"""

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

__all__ = [
    "SYSTEM_PROMPT_DYNAMIC_BOUNDARY",
    "ContextFile",
    "ModelFamilyIdentity",
    "NoteEntry",
    "ProjectContext",
    "SystemPromptBuilder",
    "load_system_prompt",
]
