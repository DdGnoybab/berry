"""Skill tool — load a skill definition and inject its prompt into context.

Mirrors claw-code's Skill tool (reference/claw-code_1/rust/crates/tools/src/lib.rs):
  1. Resolve skill name to a file path (search .berry/skills/, ~/.berry/skills/, cwd)
  2. Read the markdown file
  3. Return the prompt content (LLM then follows the instructions)

Skills are markdown files with optional YAML frontmatter:
    ---
    name: brainstorming
    description: "..."
    ---

    # Skill content here...
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar

from berry.core.tools.base import Tool, ToolContext

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

_SKILL_FILE_NAMES = ["SKILL.md", "skill.md"]


class SkillTool:
    """Load a local skill definition and its instructions."""

    name: ClassVar[str] = "skill"
    description: ClassVar[str] = (
        "Load a skill by name. The skill's instructions are returned as text "
        "that guides your behavior for the current task. Use this when a task "
        "matches a known skill pattern."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "The skill name or path to load.",
            },
            "args": {
                "type": "string",
                "description": "Optional arguments passed to the skill.",
            },
        },
        "required": ["skill"],
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        """Resolve and load the skill, returning its content."""
        skill_name = args.get("skill", "").strip()
        skill_args = args.get("args")

        if not skill_name:
            return "Error: skill name must not be empty"

        skill_path = _resolve_skill_path(skill_name, ctx.cwd)
        if skill_path is None:
            available = _list_available_skills(ctx.cwd)
            msg = f"Error: unknown skill: {skill_name}"
            if available:
                msg += f"\n\nAvailable skills: {', '.join(available)}"
            return msg

        try:
            content = skill_path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Error: cannot read skill file {skill_path}: {exc}"

        description = _parse_description(content)
        prompt = _strip_frontmatter(content)

        # Build output matching claw-code's SkillOutput shape
        lines = [
            f"Skill: {skill_name}",
            f"Path: {skill_path}",
        ]
        if description:
            lines.append(f"Description: {description}")
        if skill_args:
            lines.append(f"Arguments: {skill_args}")
        lines.append("")
        lines.append(prompt)

        return "\n".join(lines)


def _resolve_skill_path(skill_name: str, cwd: Path) -> Path | None:
    """Search for a skill file in standard locations.

    Search order (matches claw-code):
      1. Project-local: <cwd>/.berry/skills/<name>/
      2. User-global: ~/.berry/skills/<name>/
      3. Direct path (if skill_name looks like a path)
    """
    normalized = skill_name.strip().lstrip("/")
    if not normalized:
        return None

    # Search roots
    roots = _skill_lookup_roots(cwd)
    for root in roots:
        found = _find_skill_in_root(root, normalized)
        if found is not None:
            return found

    # Direct path fallback
    direct = Path(normalized)
    if direct.is_absolute() and direct.is_file():
        return direct
    relative = cwd / normalized
    if relative.is_file():
        return relative

    return None


def _skill_lookup_roots(cwd: Path) -> list[Path]:
    """Return skill search roots in priority order."""
    roots: list[Path] = []

    # Project-local
    project_skills = cwd / ".berry" / "skills"
    if project_skills.is_dir():
        roots.append(project_skills)

    # Walk up to find project root with .berry/
    current = cwd.parent
    while current != current.parent:
        candidate = current / ".berry" / "skills"
        if candidate.is_dir() and candidate != project_skills:
            roots.append(candidate)
            break
        current = current.parent

    # User-global
    home_skills = Path.home() / ".berry" / "skills"
    if home_skills.is_dir():
        roots.append(home_skills)

    return roots


def _find_skill_in_root(root: Path, name: str) -> Path | None:
    """Look for a skill by name within a root directory.

    Tries:
      - <root>/<name>/SKILL.md
      - <root>/<name>.md
    """
    # Directory with SKILL.md inside
    skill_dir = root / name
    if skill_dir.is_dir():
        for filename in _SKILL_FILE_NAMES:
            skill_file = skill_dir / filename
            if skill_file.is_file():
                return skill_file

    # Direct .md file
    md_file = root / f"{name}.md"
    if md_file.is_file():
        return md_file

    return None


def _list_available_skills(cwd: Path) -> list[str]:
    """List skill names available from all roots."""
    skills: list[str] = []
    roots = _skill_lookup_roots(cwd)

    for root in roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.is_dir():
                for filename in _SKILL_FILE_NAMES:
                    if (entry / filename).is_file():
                        skills.append(entry.name)
                        break
            elif entry.suffix == ".md" and entry.stem not in skills:
                skills.append(entry.stem)

    return sorted(set(skills))


def _parse_description(content: str) -> str | None:
    """Extract description from YAML frontmatter if present."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None

    frontmatter = match.group(1)
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            value = line[len("description:"):].strip()
            return value.strip("\"'")

    return None


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from skill content."""
    match = _FRONTMATTER_RE.match(content)
    if match:
        return content[match.end():]
    return content
