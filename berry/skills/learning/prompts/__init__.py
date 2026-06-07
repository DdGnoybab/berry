"""System prompt fragments for the learning assistant.

The full system prompt is assembled by ``berry/core/agent/prompt.py`` from:
  - core base prompt (claw-code style)
  - learning persona (system.md in this dir)
  - workspace LEARNER.md (loaded at runtime per workspace)
  - .berry/skills/learning/SKILL.md (loaded as a skill module by the runtime)
"""
