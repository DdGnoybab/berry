"""Core helpers that work alongside the skill files in ``berry/skills/``.

This is NOT the skills directory itself (those are markdown files under
``berry/skills/<name>/``). This subpackage holds the engine-side
machinery for loading, activating, and reasoning about skills:

  - ``learning_persona``: build a workspace-aware system-prompt
    increment when the active project is a learning project.

The split mirrors how Claude Code separates the SkillTool runtime
plumbing from the SKILL.md content.
"""
