"""Packaged SKILL.md for the learning assistant.

The SKILL.md sibling to this file is the source of truth — it ships inside
the ``berry`` Python package so a ``pip install berry`` includes it.

At runtime, ``init_workspace.sync_skill_to_user_dir()`` copies it to
``~/.berry/skills/learning/SKILL.md`` so the LLM's ``skill`` tool can resolve
``skill="learning"`` from any workspace cwd.
"""

from pathlib import Path

SKILL_MD_PATH = Path(__file__).parent / "SKILL.md"
