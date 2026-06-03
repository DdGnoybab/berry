"""GrepSearchTool + GlobSearchTool — file content and name searching.

Mirrors claw-code's grep_search / glob_search tools.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext
from berry.core.tools.files.path_scope import normalize_path_allow_missing, validate_workspace_boundary


class GrepSearchTool:
    """Search file contents with a regex pattern."""

    name: ClassVar[str] = "grep_search"
    description: ClassVar[str] = (
        "Search file contents with a regex pattern. "
        "Returns matching lines with file paths and line numbers."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search in. Defaults to workspace root.",
            },
            "glob": {
                "type": "string",
                "description": "File glob filter (e.g. '*.py').",
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        pattern = args["pattern"]
        search_path = args.get("path", ".")
        file_glob = args.get("glob")

        if not pattern:
            return "Error: pattern must not be empty"

        # Resolve path within workspace
        resolved = _resolve_in_workspace(search_path, ctx.cwd)
        if resolved is None:
            return f"Error: path '{search_path}' is outside workspace"

        # Build ripgrep or fallback to grep
        cmd = _build_grep_command(pattern, str(resolved), file_glob)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(ctx.cwd),
            )
        except subprocess.TimeoutExpired:
            return "Error: search timed out after 30s"
        except FileNotFoundError:
            # Fallback: use Python-based grep
            return _python_grep(pattern, resolved, file_glob)

        output = proc.stdout.rstrip()
        if not output:
            return "No matches found."

        # Truncate if too long
        lines = output.splitlines()
        if len(lines) > 100:
            return "\n".join(lines[:100]) + f"\n\n... ({len(lines) - 100} more matches truncated)"

        return output


class GlobSearchTool:
    """Find files by glob pattern."""

    name: ClassVar[str] = "glob_search"
    description: ClassVar[str] = (
        "Find files by glob pattern. Returns matching file paths relative to workspace."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to workspace root.",
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        pattern = args["pattern"]
        search_path = args.get("path", ".")

        if not pattern:
            return "Error: pattern must not be empty"

        resolved = _resolve_in_workspace(search_path, ctx.cwd)
        if resolved is None:
            return f"Error: path '{search_path}' is outside workspace"

        matches = _glob_files(resolved, pattern)

        if not matches:
            return "No files found."

        # Return relative paths
        results: list[str] = []
        for m in matches[:200]:
            try:
                rel = m.relative_to(ctx.cwd)
            except ValueError:
                rel = m
            results.append(str(rel))

        output = "\n".join(results)
        if len(matches) > 200:
            output += f"\n\n... ({len(matches) - 200} more files truncated)"

        return output


def _resolve_in_workspace(path: str, workspace: Path) -> Path | None:
    """Resolve a path relative to workspace, return None if outside."""
    try:
        resolved = normalize_path_allow_missing(path, workspace)
        validate_workspace_boundary(resolved, workspace)
        return resolved
    except Exception:
        return None


def _build_grep_command(pattern: str, path: str, file_glob: str | None) -> list[str]:
    """Build grep command, preferring ripgrep if available."""
    # Try ripgrep first
    cmd = ["rg", "--no-heading", "--line-number", "--color=never"]
    if file_glob:
        cmd.extend(["--glob", file_glob])
    cmd.extend([pattern, path])
    return cmd


def _python_grep(pattern: str, search_path: Path, file_glob: str | None) -> str:
    """Fallback grep implementation in pure Python."""
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regex pattern: {exc}"

    results: list[str] = []
    files = _collect_files(search_path, file_glob)

    for filepath in files[:500]:
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                try:
                    rel = filepath.relative_to(search_path)
                except ValueError:
                    rel = filepath
                results.append(f"{rel}:{lineno}:{line.rstrip()}")

                if len(results) >= 100:
                    results.append(f"\n... (truncated at 100 matches)")
                    return "\n".join(results)

    if not results:
        return "No matches found."

    return "\n".join(results)


def _collect_files(root: Path, file_glob: str | None) -> list[Path]:
    """Collect files under root, optionally filtered by glob."""
    if root.is_file():
        return [root]

    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if file_glob and not fnmatch.fnmatch(path.name, file_glob):
            continue
        files.append(path)

    return sorted(files)[:1000]


def _glob_files(root: Path, pattern: str) -> list[Path]:
    """Find files matching a glob pattern."""
    matches: list[Path] = []
    for path in root.glob(pattern):
        if path.is_file():
            matches.append(path)
    return sorted(matches)
