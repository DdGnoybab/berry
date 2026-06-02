"""Pure file IO functions for the read/write/edit_file tools.

Mirrors claw-code (reference/claw-code_1/rust/crates/runtime/src/file_ops.rs)
1:1 in shape, with one deliberate divergence in :func:`edit_file_in_workspace`
(see spec § 11 ADR — multi-match without replace_all is rejected, not silently
replacing the first occurrence).

Naming: each function takes ``workspace`` (cwd) and is *boundary-aware* — they
all call :func:`validate_workspace_boundary` before touching the filesystem.

Output schemas are dicts ready for ``json.dumps``; keys use camelCase to match
claw-code's ``serde(rename = "...")`` declarations so any tool consumer
written against claw-code's JSON works without translation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from berry.core.tools.files.path_scope import (
    normalize_path,
    normalize_path_allow_missing,
    validate_workspace_boundary,
)

# Hard caps mirror claw-code (file_ops.rs:14 / file_ops.rs:17).
MAX_READ_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_WRITE_SIZE = 10 * 1024 * 1024  # 10 MB

# Read first this many bytes when sniffing for binary content.
_BINARY_PROBE_BYTES = 8 * 1024


# ─── read ──────────────────────────────────────────────────────────────────


def read_file_in_workspace(
    path: str,
    offset: int | None,
    limit: int | None,
    workspace: Path,
) -> dict[str, Any]:
    """Read a text file, return claw-code-compatible payload.

    ``offset`` / ``limit`` are line indices (not bytes); empty offset reads
    from line 0, empty limit reads to EOF. Mirrors ``read_file`` in
    file_ops.rs:185 + ``read_file_in_workspace`` at file_ops.rs:678.
    """
    absolute = normalize_path(path, workspace)
    validate_workspace_boundary(absolute, workspace)

    size = absolute.stat().st_size
    if size > MAX_READ_SIZE:
        raise OSError(
            f"file is too large ({size} bytes, max {MAX_READ_SIZE} bytes)"
        )

    if _is_binary(absolute):
        raise OSError("file appears to be binary")

    content = absolute.read_text(encoding="utf-8")
    # splitlines() matches Rust str::lines() — trailing newline does not
    # produce a phantom empty element. Counts line up with claw-code's.
    lines = content.splitlines()

    start_index = min(offset or 0, len(lines))
    if limit is None:
        end_index = len(lines)
    else:
        end_index = min(start_index + limit, len(lines))
    selected = "\n".join(lines[start_index:end_index])

    return {
        "type": "text",
        "file": {
            "filePath": str(absolute),
            "content": selected,
            "numLines": end_index - start_index,
            "startLine": start_index + 1,
            "totalLines": len(lines),
        },
    }


# ─── write ─────────────────────────────────────────────────────────────────


def write_file_in_workspace(
    path: str,
    content: str,
    workspace: Path,
) -> dict[str, Any]:
    """Create or overwrite a text file, returning a structured patch payload.

    Mirrors ``write_file`` in file_ops.rs:234 + ``write_file_in_workspace``
    at file_ops.rs:692.
    """
    if len(content.encode("utf-8")) > MAX_WRITE_SIZE:
        raise OSError(
            f"content is too large ({len(content.encode('utf-8'))} bytes, "
            f"max {MAX_WRITE_SIZE} bytes)"
        )

    absolute = normalize_path_allow_missing(path, workspace)
    validate_workspace_boundary(absolute, workspace)

    original = absolute.read_text(encoding="utf-8") if absolute.exists() else None
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_text(content, encoding="utf-8")

    return {
        "type": "update" if original is not None else "create",
        "filePath": str(absolute),
        "content": content,
        "structuredPatch": _make_patch(original or "", content),
        "originalFile": original,
        "gitDiff": None,
    }


# ─── edit ──────────────────────────────────────────────────────────────────


def edit_file_in_workspace(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool,
    workspace: Path,
) -> dict[str, Any]:
    """Replace ``old_string`` with ``new_string`` in a workspace file.

    Berry deliberately diverges from claw-code here: when ``replace_all`` is
    false and ``old_string`` matches more than once, we *reject* instead of
    silently replacing the first occurrence. This forces the LLM to add
    enough context to make ``old_string`` unique, which prevents the
    classic "changed the wrong line, user never noticed" failure mode.
    See spec § 11 ADR.
    """
    absolute = normalize_path(path, workspace)
    validate_workspace_boundary(absolute, workspace)

    if old_string == new_string:
        raise ValueError("old_string and new_string must differ")

    original = absolute.read_text(encoding="utf-8")
    if old_string not in original:
        raise ValueError("old_string not found in file")

    occurrences = original.count(old_string)
    # ⚠️ Diverges from claw-code on purpose (see spec § 11 ADR).
    if not replace_all and occurrences > 1:
        raise ValueError(
            f"old_string appears {occurrences} times in file, "
            "narrow it down with more context or set replace_all=true"
        )

    if replace_all:
        updated = original.replace(old_string, new_string)
    else:
        updated = original.replace(old_string, new_string, 1)
    absolute.write_text(updated, encoding="utf-8")

    return {
        "filePath": str(absolute),
        "oldString": old_string,
        "newString": new_string,
        "originalFile": original,
        "structuredPatch": _make_patch(original, updated),
        "userModified": False,
        "replaceAll": replace_all,
        "gitDiff": None,
    }


# ─── internals ─────────────────────────────────────────────────────────────


def _is_binary(path: Path) -> bool:
    """Treat any file with NUL bytes in the first 8 KB as binary.

    Matches claw-code's heuristic (file_ops.rs:30).
    """
    with path.open("rb") as f:
        chunk = f.read(_BINARY_PROBE_BYTES)
    return b"\x00" in chunk


def _make_patch(original: str, updated: str) -> list[dict[str, Any]]:
    """Build a single-hunk structured patch (whole-file - / + listing).

    Claw-code uses the same simplified shape (file_ops.rs:626). Real unified
    diff output is a future improvement; what we return today already meets
    the JSON schema downstream consumers expect.
    """
    original_lines = original.splitlines()
    updated_lines = updated.splitlines()
    lines: list[str] = []
    for line in original_lines:
        lines.append(f"-{line}")
    for line in updated_lines:
        lines.append(f"+{line}")
    return [
        {
            "oldStart": 1,
            "oldLines": len(original_lines),
            "newStart": 1,
            "newLines": len(updated_lines),
            "lines": lines,
        }
    ]


__all__ = [
    "MAX_READ_SIZE",
    "MAX_WRITE_SIZE",
    "edit_file_in_workspace",
    "read_file_in_workspace",
    "write_file_in_workspace",
]
