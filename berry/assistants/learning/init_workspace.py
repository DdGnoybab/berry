"""Bootstrap a learning workspace + sync the SKILL definition.

Two responsibilities:

1. **Ensure a workspace skeleton exists** —— ``<workspace>/.berry/`` and a
   starter ``LEARNER.md`` template. Idempotent: never overwrite user content.
2. **Sync the packaged SKILL.md to ~/.berry/skills/learning/SKILL.md** so the
   LLM's ``skill`` tool can resolve ``skill="learning"`` from any cwd.

This is run once at berry-feishu startup (and is safe to call repeatedly).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from berry.assistants.learning.skill import SKILL_MD_PATH
from berry.observability.logging import get_logger

logger = get_logger(__name__)


_LEARNER_MD_TEMPLATE = """\
# Learner Profile

> 这份文件由 berry-L 学习助手读取作为 system prompt 的一部分。
> 你可以随时编辑它,下次会话生效。

## 背景
(简单说说你的技术背景。例:后端工程师,5 年 Java 经验,熟数据结构与系统设计。)

## 目标
(你想从这次学习里得到什么?例:面试 Redis 中级岗,能扛住底层实现追问。)

## 节奏
(每次想花多久?多久学一次?例:每天 20-30 分钟,周末 1 小时。)

## 偏好
(你喜欢什么风格的讲解?有什么红线?例:用 Java 类比讲、不要直接给答案先 hint。)
"""


def sync_skill_to_user_dir(user_skill_dir: Path | None = None) -> Path:
    """Copy the packaged learning SKILL.md into the user-global skills dir.

    Default destination: ``~/.berry/skills/learning/SKILL.md``.

    Always copies (overwrites) — the packaged version is authoritative; if
    the user wants overrides they should put them in ``<workspace>/.berry/skills/``
    which takes precedence per ``berry.core.tools.core.skill._skill_lookup_roots``.

    Returns the path written.
    """
    target_dir = user_skill_dir or (Path.home() / ".berry" / "skills" / "learning")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "SKILL.md"
    if not SKILL_MD_PATH.is_file():
        logger.warning(
            "learning_skill_source_missing",
            path=str(SKILL_MD_PATH),
            note="Packaged SKILL.md not found; learning skill will not be resolvable.",
        )
        return target
    try:
        shutil.copyfile(SKILL_MD_PATH, target)
    except OSError as exc:
        logger.warning(
            "learning_skill_sync_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            target=str(target),
        )
        return target
    logger.info("learning_skill_synced", target=str(target))
    return target


def ensure_workspace_skeleton(workspace_path: Path) -> None:
    """Create ``.berry/`` and write a starter ``LEARNER.md`` if absent.

    Idempotent. Never overwrites existing files. Any failure is logged but
    not raised — a missing skeleton just means the LLM will create it via
    ``write_file`` on first use.
    """
    try:
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / ".berry").mkdir(exist_ok=True)
    except OSError as exc:
        logger.warning(
            "learning_workspace_skeleton_failed",
            error_type=type(exc).__name__,
            error=str(exc),
            workspace=str(workspace_path),
        )
        return

    learner_md = workspace_path / "LEARNER.md"
    if not learner_md.exists():
        try:
            learner_md.write_text(_LEARNER_MD_TEMPLATE, encoding="utf-8")
            logger.info("learner_md_template_written", path=str(learner_md))
        except OSError as exc:
            logger.warning(
                "learner_md_write_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                path=str(learner_md),
            )


def init_learning_workspace(workspace_path: Path) -> None:
    """One-stop init: create skeleton + sync SKILL to user dir.

    Called at berry-feishu startup whenever ``workspace_path`` resolves
    successfully. Safe to call repeatedly.
    """
    sync_skill_to_user_dir()
    ensure_workspace_skeleton(workspace_path)
