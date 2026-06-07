"""TaskCreate / TaskGet / TaskList / TaskUpdate — 跨会话持久化的任务追踪。

与 todo_write 的区别(详见 docs/superpowers/specs/2026-06-07-task-system-design.md):
- todo_write: 当前会话的执行清单, 单文件全量, 会话结束可清空, 有飞书 UI
- task_*:    跨会话长期任务, 每任务一文件, 会话结束保留, 有依赖图, MVP 无 UI

数据模型: 7 字段(id/subject/description/activeForm/status/owner/blockedBy)
存储:     <cwd>/.berry/tasks/{id}.json — 每任务一文件
依赖:     LLM 维护 blockedBy, blocks 反向计算; 创建/更新时 DFS 检测环
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from berry.core.tools.base import ToolContext

_VALID_STATUSES = ("pending", "in_progress", "completed")
_logger = logging.getLogger(__name__)


# ==== Constants & Data ====


@dataclass
class Task:
    # mixedCase activeForm/blockedBy 与 LLM schema 和持久化 JSON 字段名保持一致,
    # 避免序列化转换层(对齐 todo.py 的 activeForm 字段命名约定)。
    id: str
    subject: str
    activeForm: str  # noqa: N815
    status: str = "pending"
    owner: str | None = None
    description: str = ""
    blockedBy: list[str] = field(default_factory=list)  # noqa: N815


# ==== Storage ====


def _tasks_dir(cwd: Path) -> Path:
    return cwd / ".berry" / "tasks"


def _task_path(cwd: Path, task_id: str) -> Path:
    return _tasks_dir(cwd) / f"{task_id}.json"


def _new_task_id() -> str:
    """task_<毫秒时间戳>_<4hex>. 单 workspace 内并发创建无碰撞。"""
    return f"task_{int(time.time() * 1000)}_{secrets.token_hex(2)}"


def _save_task(cwd: Path, task: Task) -> None:
    path = _task_path(cwd, task.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(task), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_task(cwd: Path, task_id: str) -> Task | None:
    """读取并验证任务文件; 任何失败返回 None。"""
    path = _task_path(cwd, task_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Task(**data)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        _logger.warning("failed to load task %s: %s", task_id, exc)
        return None


def _list_all_tasks(cwd: Path) -> list[Task]:
    """扫目录加载所有 task。损坏文件已在 _load_task 内跳过并 log。"""
    d = _tasks_dir(cwd)
    if not d.is_dir():
        return []
    out: list[Task] = []
    for path in sorted(d.glob("task_*.json")):
        task_id = path.stem
        task = _load_task(cwd, task_id)
        if task is not None:
            out.append(task)
    return out


# ==== Dependency graph ====


def _compute_blocks(cwd: Path, task_id: str) -> list[str]:
    """反向: 谁的 blockedBy 包含 task_id。"""
    return [t.id for t in _list_all_tasks(cwd) if task_id in t.blockedBy]


def _can_start(cwd: Path, task: Task) -> tuple[bool, list[str]]:
    """返回 (能否开始, blocker id 列表)。不存在的 dep 也算 blocker。"""
    blockers: list[str] = []
    for dep_id in task.blockedBy:
        dep = _load_task(cwd, dep_id)
        if dep is None or dep.status != "completed":
            blockers.append(dep_id)
    return (not blockers, blockers)


def _unblocked_after(cwd: Path, completed_id: str) -> list[Task]:
    """完成 completed_id 后,在 pending 任务里找出 blockedBy 全 completed 的下游。"""
    out: list[Task] = []
    for t in _list_all_tasks(cwd):
        if t.status != "pending" or completed_id not in t.blockedBy:
            continue
        ok, _ = _can_start(cwd, t)
        if ok:
            out.append(t)
    return out


def _detect_cycle(
    cwd: Path,
    *,
    candidate_id: str,
    candidate_blocked_by: list[str],
) -> list[str] | None:
    """三色 DFS。在「假设把 candidate 加进图」前提下检测环,返回环路径或 None。"""
    graph: dict[str, list[str]] = {
        t.id: list(t.blockedBy) for t in _list_all_tasks(cwd)
    }
    graph[candidate_id] = list(candidate_blocked_by)

    # 三色标记: 0=white(未访问), 1=gray(在当前 DFS 栈), 2=black(已完成)
    white, gray, black = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(graph, white)
    parent: dict[str, str] = {}

    def dfs(node: str) -> list[str] | None:
        color[node] = gray
        for dep in graph.get(node, []):
            if dep not in color:
                continue  # dep 不在图里(create 时另校验存在性)
            if color[dep] == gray:
                return _build_cycle_path(parent, node, dep)
            if color[dep] == white:
                parent[dep] = node
                cycle = dfs(dep)
                if cycle:
                    return cycle
        color[node] = black
        return None

    return dfs(candidate_id)


def _build_cycle_path(parent: dict[str, str], start: str, target: str) -> list[str]:
    """从 start 沿 parent 链回溯到 target,得到一条 target -> ... -> start -> target 的环。"""
    path = [start]
    node = start
    while node != target and node in parent:
        node = parent[node]
        path.append(node)
    path.append(start)
    return list(reversed(path))


# ==== Helpers ====


def _resolve_owner(ctx: ToolContext, explicit: str | None) -> str:
    """显式优先; 否则 user_id → session_id → 'agent'。"""
    if explicit is not None:
        return explicit
    if ctx.user_id is not None:
        return str(ctx.user_id)
    return ctx.session_id or "agent"


# Sentinel: 区分「没传 owner 字段」与「显式传 owner=None」
_OWNER_UNSET: Any = object()


_LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress", "completed"},
    "in_progress": {"completed", "pending"},
    "completed": set(),  # 终态
}


def _check_transition(
    ctx: ToolContext,
    task: Task,
    new_status: str,
    explicit_owner: Any,
) -> str | None:
    """状态机校验。返回错误消息或 None; 副作用: 在 pending→in_progress 时填 owner。"""
    old_status = task.status
    if new_status == old_status:
        return None  # 同状态 update 当作 no-op(允许 patch 其他字段)
    if new_status not in _LEGAL_TRANSITIONS.get(old_status, set()):
        return (
            f"Error: illegal transition {old_status} → {new_status} "
            f"(completed is terminal)"
        )
    if old_status == "pending" and new_status == "in_progress":
        ok, blockers = _can_start(ctx.cwd, task)
        if not ok:
            return f"Error: blocked by: {blockers}"
        # auto-fill owner
        if explicit_owner is _OWNER_UNSET and task.owner is None:
            task.owner = _resolve_owner(ctx, None)
    return None


def _format_update_msg(task: Task, old_status: str, new_status: str | None) -> str:
    parts = [f"Updated {task.id}"]
    if new_status is not None and new_status != old_status:
        parts.append(f"status {old_status} → {new_status}")
        if new_status == "in_progress" and task.owner:
            parts.append(f"claimed by {task.owner}")
    return ": ".join(parts) if len(parts) > 1 else parts[0]


def _format_list_item(task: Task) -> str:
    """task_xxx [status] subject  (blockedBy: N)  ← owner

    blockedBy 段仅在有上游时出现; owner 段仅在 in_progress 时出现。
    """
    line = f"{task.id} [{task.status}] {task.subject}"
    if task.blockedBy:
        line += f"  (blockedBy: {len(task.blockedBy)})"
    if task.status == "in_progress" and task.owner:
        line += f"  ← {task.owner}"
    return line


# ==== Tools ====


class TaskCreateTool:
    name: ClassVar[str] = "task_create"
    description: ClassVar[str] = (
        "Create a long-running task that persists across sessions. "
        "Use this for goals tracked over time, not for in-session execution "
        "checklists (use todo_write for those)."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "activeForm": {"type": "string"},
            "blockedBy": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["subject", "activeForm"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        subject = args.get("subject", "")
        active_form = args.get("activeForm", "")
        description = args.get("description", "")
        blocked_by = list(args.get("blockedBy") or [])

        if not subject.strip():
            return "Error: subject must not be empty"
        if not active_form.strip():
            return "Error: activeForm must not be empty"

        # 校验上游存在
        for dep_id in blocked_by:
            if _load_task(ctx.cwd, dep_id) is None:
                return f"Error: unknown blockedBy: {dep_id}"

        new_id = _new_task_id()

        # 循环检测(虽然新 id 当前不被任何任务依赖,但理论上 blocked_by 自身可能成环)
        cycle = _detect_cycle(
            ctx.cwd, candidate_id=new_id, candidate_blocked_by=blocked_by
        )
        if cycle is not None:
            return f"Error: cycle detected: {' -> '.join(cycle)}"

        task = Task(
            id=new_id,
            subject=subject,
            activeForm=active_form,
            description=description,
            status="pending",
            owner=None,
            blockedBy=blocked_by,
        )
        _save_task(ctx.cwd, task)
        return f"Created {task.id}: {subject}"


class TaskGetTool:
    name: ClassVar[str] = "task_get"
    description: ClassVar[str] = (
        "Read a single task by id, including description and computed `blocks` "
        "(downstream tasks that depend on it)."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"taskId": {"type": "string"}},
        "required": ["taskId"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        task_id = args["taskId"]
        task = _load_task(ctx.cwd, task_id)
        if task is None:
            return f"Error: task {task_id} not found"
        data = asdict(task)
        data["blocks"] = _compute_blocks(ctx.cwd, task_id)
        return json.dumps(data, indent=2, ensure_ascii=False)


class TaskListTool:
    name: ClassVar[str] = "task_list"
    description: ClassVar[str] = (
        "List all tasks (subject + status + owner + blockedBy summary). "
        "Use task_get for full details of a specific task."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": list(_VALID_STATUSES),
                "description": "Optional filter.",
            },
        },
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        status_filter = args.get("status")
        tasks = _list_all_tasks(ctx.cwd)
        if status_filter is not None:
            tasks = [t for t in tasks if t.status == status_filter]
        if not tasks:
            return "No tasks yet."
        return "\n".join(_format_list_item(t) for t in tasks)


class TaskUpdateTool:
    name: ClassVar[str] = "task_update"
    description: ClassVar[str] = (
        "Update fields of an existing task. All fields except taskId are "
        "optional patches. Use this to claim (status=in_progress), complete "
        "(status=completed), or adjust dependencies."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "taskId": {"type": "string"},
            "status": {"type": "string", "enum": list(_VALID_STATUSES)},
            "owner": {"type": ["string", "null"]},
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "activeForm": {"type": "string"},
            "addBlockedBy": {"type": "array", "items": {"type": "string"}},
            "removeBlockedBy": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["taskId"],
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> str:
        task_id = args["taskId"]
        task = _load_task(ctx.cwd, task_id)
        if task is None:
            return f"Error: task {task_id} not found"

        old_status = task.status
        new_status = args.get("status")
        explicit_owner = args.get("owner", _OWNER_UNSET)

        # 1) 状态机校验 + owner 自动填
        if new_status is not None:
            err = _check_transition(ctx, task, new_status, explicit_owner)
            if err:
                return err
            task.status = new_status

        # 2) 依赖 patch (remove 先, add 后)
        add = list(args.get("addBlockedBy") or [])
        remove = list(args.get("removeBlockedBy") or [])
        conflict = set(add) & set(remove)
        if conflict:
            return f"Error: same id in both addBlockedBy and removeBlockedBy: {sorted(conflict)}"

        if remove:
            task.blockedBy = [b for b in task.blockedBy if b not in remove]
        if add:
            for dep_id in add:
                if _load_task(ctx.cwd, dep_id) is None:
                    return f"Error: unknown blockedBy: {dep_id}"
            merged = list(task.blockedBy) + [b for b in add if b not in task.blockedBy]
            cycle = _detect_cycle(
                ctx.cwd, candidate_id=task.id, candidate_blocked_by=merged
            )
            if cycle is not None:
                return f"Error: cycle detected: {' -> '.join(cycle)}"
            task.blockedBy = merged

        # 3) 文本字段
        if "subject" in args:
            if not args["subject"].strip():
                return "Error: subject must not be empty"
            task.subject = args["subject"]
        if "activeForm" in args:
            if not args["activeForm"].strip():
                return "Error: activeForm must not be empty"
            task.activeForm = args["activeForm"]
        if "description" in args:
            task.description = args["description"]

        # 4) owner patch (显式优先,前面状态机已处理 auto-fill)
        if explicit_owner is not _OWNER_UNSET:
            task.owner = explicit_owner

        # in_progress → pending: 释放 owner
        if (
            new_status == "pending"
            and old_status == "in_progress"
            and explicit_owner is _OWNER_UNSET
        ):
            task.owner = None

        _save_task(ctx.cwd, task)

        # 5) 返回消息
        msg = _format_update_msg(task, old_status, new_status)
        if new_status == "completed":
            unblocked = _unblocked_after(ctx.cwd, task.id)
            if unblocked:
                msg += "\nUnblocked: " + ", ".join(
                    f"{t.id} ({t.subject})" for t in unblocked
                )
        return msg
