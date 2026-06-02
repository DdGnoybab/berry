"""Snapshot test: render a full system prompt with fixture data and diff
against a golden file.

Why fixture-only: the prompt embeds cwd / current_date / Berry version /
platform — letting real values in would make the snapshot machine-specific
and force a golden update on every run. Instead we feed normalized inputs
and assert the entire output verbatim.

Updating the golden:
- When you intentionally change static text or render layout, run
  ``UPDATE_GOLDEN=1 pytest tests/unit/assistants/learning/prompts/test_snapshot.py``
  and review the diff before committing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from berry.assistants.learning.prompts import (
    ContextFile,
    ModelFamilyIdentity,
    NoteEntry,
    ProjectContext,
    SystemPromptBuilder,
)
from berry.assistants.learning.prompts.progress_parser import (
    Milestone,
    ProgressSnapshot,
    SmallGoal,
)

GOLDEN_PATH = Path(__file__).parent / "snapshots" / "system_prompt_full.md"


@pytest.fixture
def fixture_project_context() -> ProjectContext:
    """Stable, machine-independent project context."""
    return ProjectContext(
        cwd=Path("/tmp/test-project"),
        current_date="2026-01-01",
        notes_dir="notes",
        notes_index=[
            NoteEntry(
                relpath="notes/01-redis-basics.md",
                last_modified="2025-12-29",
                size_bytes=3200,
                is_empty=False,
            ),
            NoteEntry(
                relpath="notes/02-redis-data-types.md",
                last_modified="2025-12-30",
                size_bytes=5120,
                is_empty=False,
            ),
            NoteEntry(
                relpath="notes/03-redis-persistence.md",
                last_modified="2025-12-30",
                size_bytes=0,
                is_empty=True,
            ),
        ],
        instruction_files=[
            ContextFile(
                path=Path("/tmp/test-project/BERRY.md"),
                content=(
                    "# Berry rules for the redis study project\n\n"
                    "- 我是后端工程师,Redis 基础命令(GET/SET/EXPIRE/TTL)不用从头讲。\n"
                    "- 例子用 Python(redis-py)。\n"
                ),
            ),
        ],
        progress=ProgressSnapshot(
            goal="深入理解 Redis,能应对深层追问",
            milestones=[
                Milestone(
                    index=1,
                    title="数据结构原理",
                    status="in_progress",
                    criterion="能解释 5 个核心结构 + 各自性能权衡",
                    small_goals=[
                        SmallGoal(
                            index="1.1",
                            title="SDS — 设计原理与权衡",
                            status="done",
                            score=9.5,
                        ),
                        SmallGoal(
                            index="1.2",
                            title="ziplist / listpack — 紧凑结构的演进",
                            status="in_progress",
                        ),
                        SmallGoal(
                            index="1.3",
                            title="quicklist — List 的双层结构",
                            status="pending",
                        ),
                    ],
                ),
                Milestone(
                    index=2,
                    title="过期与内存管理",
                    status="pending",
                    criterion="解释 6 种淘汰策略 + 写出过期检查的两阶段流程",
                ),
            ],
        ),
        quizzes_index=[
            NoteEntry(
                relpath="quizzes/m1.1-q1.md",
                last_modified="2026-01-01",
                size_bytes=512,
                is_empty=False,
            ),
        ],
        references_index=[
            NoteEntry(
                relpath="references/redis-design-and-implementation.md",
                last_modified="2025-12-28",
                size_bytes=10240,
                is_empty=False,
            ),
        ],
    )


def _render_full_prompt(ctx: ProjectContext) -> str:
    """Render with the same args we'd pass at runtime, but all fixture-pinned."""
    sections = (
        SystemPromptBuilder()
        .with_os("darwin", "25.5.0")
        .with_model_family(ModelFamilyIdentity.CLAUDE)
        .with_berry_version("0.0.3")
        .with_project_context(ctx)
        .with_runtime_config(
            {
                "language": "zh-CN",
                "notes_dir": "notes",
            },
        )
        .build()
    )
    return "\n\n".join(sections)


def test_full_system_prompt_matches_golden(
    fixture_project_context: ProjectContext,
) -> None:
    rendered = _render_full_prompt(fixture_project_context)

    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(rendered, encoding="utf-8")
        pytest.skip("Golden updated; rerun without UPDATE_GOLDEN to verify.")

    if not GOLDEN_PATH.exists():
        # First-run convenience: write the golden, fail loudly so a human
        # explicitly approves it on the next run.
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(rendered, encoding="utf-8")
        pytest.fail(
            f"Golden file did not exist; wrote {GOLDEN_PATH}. "
            "Inspect it and rerun the test."
        )

    expected = GOLDEN_PATH.read_text(encoding="utf-8")
    assert rendered == expected, (
        "Rendered system prompt diverges from golden. "
        "If this change is intentional, rerun with UPDATE_GOLDEN=1 to refresh "
        f"{GOLDEN_PATH}."
    )
