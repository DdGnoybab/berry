"""Workspace-aware system-prompt increment for the learning skill.

When the LLM is operating inside a workspace that has been initialised
as a learning project (i.e. ``.berry/progress.json`` exists), append:

  1. The learning persona (``berry/skills/learning/prompts/system.md``)
  2. The current ``LEARNER.md`` content (goal / profile)
  3. A bootstrap directive: "EVERY turn, FIRST tool call must be
     ``skill('learning')``" — the linchpin that wires the system
     prompt to the SKILL.md state machine.

For non-learning workspaces (no progress.json) this returns the base
prompt unchanged.

Why per-turn rather than at startup:
  Web supports multiple Projects in one process. The active workspace
  changes when the user clicks a different Project in the sidebar, so
  the prompt has to recompute per turn (cheap — three small file
  reads). Feishu used to bake the persona at startup because it had
  one workspace; we keep that behaviour byte-identical when called
  with the same workspace path.
"""

from __future__ import annotations

from pathlib import Path

from berry.observability.logging import get_logger

logger = get_logger(__name__)


# Resolve the persona path relative to the berry package, so it works
# both in source checkout and after `pip install`.
_PERSONA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "skills" / "learning" / "prompts" / "system.md"
)


_BOOTSTRAP_INSTRUCTION = (
    "\n\n# Learning Mode (ACTIVE)\n\n"
    "This workspace is configured for the berry-L learning assistant.\n\n"
    "**On EVERY turn**, your FIRST tool call MUST be invoking the `skill` "
    'tool with `skill="learning"` to load the state machine rules. '
    "Treat the loaded SKILL.md as a HARD CONTRACT — its instructions "
    "override any default behavior you would otherwise apply.\n\n"
    'Do NOT skip this step "because you remember the rules" — the file '
    "is the source of truth, conversation memory is not. Read it every turn."
)


def is_learning_workspace(workspace_path: Path) -> bool:
    """A workspace counts as 'learning mode' iff it has progress.json."""
    return (workspace_path / ".berry" / "progress.json").is_file()


def augment_system_prompt(base_prompt: str, workspace_path: Path) -> str:
    """Return ``base_prompt`` augmented with learning persona, LEARNER.md,
    and the bootstrap directive.

    No-op if ``workspace_path`` is not a learning workspace.
    """
    if not is_learning_workspace(workspace_path):
        return base_prompt

    parts: list[str] = [base_prompt]

    # 1. persona
    if _PERSONA_PATH.is_file():
        try:
            parts.append("\n\n" + _PERSONA_PATH.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning(
                "learning_persona_read_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

    # 2. LEARNER.md (if present)
    learner_md = workspace_path / "LEARNER.md"
    if learner_md.is_file():
        try:
            content = learner_md.read_text(encoding="utf-8").strip()
            if content:
                parts.append(
                    "\n\n# Learner Profile (loaded from workspace LEARNER.md)\n\n"
                    + content
                )
        except OSError as exc:
            logger.warning(
                "learner_md_read_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

    # 3. bootstrap directive
    parts.append(_BOOTSTRAP_INSTRUCTION)

    return "".join(parts)
