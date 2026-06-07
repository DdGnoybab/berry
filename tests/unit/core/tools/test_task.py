"""TaskCreate / TaskGet / TaskList / TaskUpdate 工具测试。

Spec: docs/superpowers/specs/2026-06-07-task-system-design.md

设计回顾:
- 7 字段(id/subject/description/activeForm/status/owner/blockedBy)
- 单任务一文件: <cwd>/.berry/tasks/{id}.json
- LLM 维护 blockedBy, blocks 反向计算
- 创建/更新时 DFS 检测环
- 状态机: pending → in_progress → completed; in_progress ↔ pending 释放认领
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from berry.core.tools.base import ToolContext
from berry.core.tools.core.task import (
    Task,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
    _can_start,
    _compute_blocks,
    _list_all_tasks,
    _load_task,
    _new_task_id,
    _save_task,
    _tasks_dir,
    _unblocked_after,
)


def _ctx(cwd: Path) -> ToolContext:
    return ToolContext(
        session_id="test-session",
        user_id=uuid4(),
        db=None,
        data_root=cwd,
        cwd=cwd,
    )


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def ctx(workspace: Path) -> ToolContext:
    return _ctx(workspace)


# ==== Storage ====


class TestStorage:
    def test_new_task_id_format(self) -> None:
        tid = _new_task_id()
        assert re.fullmatch(r"task_\d{13}_[0-9a-f]{4}", tid), tid

    def test_save_and_load_roundtrip(self, workspace: Path) -> None:
        task = Task(
            id="task_0000000000001_aabb",
            subject="Setup DB",
            activeForm="Setting up DB",
            description="initial schema",
            status="pending",
            owner=None,
            blockedBy=["task_0000000000000_0001"],
        )
        _save_task(workspace, task)
        loaded = _load_task(workspace, task.id)
        assert loaded == task

    def test_load_task_returns_none_when_missing(self, workspace: Path) -> None:
        assert _load_task(workspace, "task_does_not_exist") is None


# ==== task_create ====


class TestCreate:
    @pytest.fixture()
    def tool(self) -> TaskCreateTool:
        return TaskCreateTool()

    @pytest.mark.asyncio
    async def test_create_minimal(
        self, tool: TaskCreateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        result = await tool.execute(
            {"subject": "Setup DB", "activeForm": "Setting up DB"}, ctx
        )
        assert result.startswith("Created task_")
        assert "Setup DB" in result

        tasks = _list_all_tasks(workspace)
        assert len(tasks) == 1
        t = tasks[0]
        assert t.subject == "Setup DB"
        assert t.activeForm == "Setting up DB"
        assert t.description == ""
        assert t.status == "pending"
        assert t.owner is None
        assert t.blockedBy == []

    @pytest.mark.asyncio
    async def test_create_with_description_and_blocked_by(
        self, tool: TaskCreateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        # 先建一个上游
        upstream = await tool.execute(
            {"subject": "Schema", "activeForm": "Building schema"}, ctx
        )
        upstream_id = upstream.split()[1].rstrip(":")

        result = await tool.execute(
            {
                "subject": "API",
                "activeForm": "Building API",
                "description": "REST endpoints over schema",
                "blockedBy": [upstream_id],
            },
            ctx,
        )
        assert result.startswith("Created task_")
        tasks = _list_all_tasks(workspace)
        api = next(t for t in tasks if t.subject == "API")
        assert api.description == "REST endpoints over schema"
        assert api.blockedBy == [upstream_id]

    @pytest.mark.asyncio
    async def test_create_rejects_empty_subject(
        self, tool: TaskCreateTool, ctx: ToolContext
    ) -> None:
        result = await tool.execute(
            {"subject": "  ", "activeForm": "Doing something"}, ctx
        )
        assert "Error" in result and "subject" in result

    @pytest.mark.asyncio
    async def test_create_rejects_empty_active_form(
        self, tool: TaskCreateTool, ctx: ToolContext
    ) -> None:
        result = await tool.execute({"subject": "X", "activeForm": ""}, ctx)
        assert "Error" in result and "activeForm" in result

    @pytest.mark.asyncio
    async def test_create_rejects_unknown_blocked_by(
        self, tool: TaskCreateTool, ctx: ToolContext
    ) -> None:
        result = await tool.execute(
            {
                "subject": "X",
                "activeForm": "Doing X",
                "blockedBy": ["task_nonexistent_aaaa"],
            },
            ctx,
        )
        assert "Error" in result and "task_nonexistent_aaaa" in result


# ==== task_get ====


class TestGet:
    @pytest.fixture()
    def create_tool(self) -> TaskCreateTool:
        return TaskCreateTool()

    @pytest.fixture()
    def get_tool(self) -> TaskGetTool:
        return TaskGetTool()

    @pytest.mark.asyncio
    async def test_get_returns_full_fields_with_computed_blocks(
        self, create_tool: TaskCreateTool, get_tool: TaskGetTool, ctx: ToolContext
    ) -> None:
        a = await create_tool.execute(
            {"subject": "A", "activeForm": "Doing A"}, ctx
        )
        a_id = a.split()[1].rstrip(":")

        await create_tool.execute(
            {"subject": "B", "activeForm": "Doing B", "blockedBy": [a_id]}, ctx
        )
        await create_tool.execute(
            {"subject": "C", "activeForm": "Doing C", "blockedBy": [a_id]}, ctx
        )

        result = await get_tool.execute({"taskId": a_id}, ctx)
        data = json.loads(result)
        assert data["id"] == a_id
        assert data["subject"] == "A"
        assert data["activeForm"] == "Doing A"
        assert data["status"] == "pending"
        assert data["owner"] is None
        assert data["blockedBy"] == []
        # blocks: B 和 C 都依赖 A
        assert len(data["blocks"]) == 2

    @pytest.mark.asyncio
    async def test_get_unknown_id_returns_error(
        self, get_tool: TaskGetTool, ctx: ToolContext
    ) -> None:
        result = await get_tool.execute({"taskId": "task_missing_xxxx"}, ctx)
        assert "Error" in result and "task_missing_xxxx" in result


class TestComputeBlocks:
    def test_compute_blocks_reverse_lookup(self, workspace: Path) -> None:
        a = Task(id="task_a", subject="A", activeForm="A")
        b = Task(id="task_b", subject="B", activeForm="B", blockedBy=["task_a"])
        c = Task(id="task_c", subject="C", activeForm="C", blockedBy=["task_a"])
        for t in (a, b, c):
            _save_task(workspace, t)

        blocks = _compute_blocks(workspace, "task_a")
        # 排序稳定: glob 按文件名 sorted
        assert blocks == ["task_b", "task_c"]
        assert _compute_blocks(workspace, "task_b") == []


# ==== task_list ====


class TestList:
    @pytest.fixture()
    def list_tool(self) -> TaskListTool:
        return TaskListTool()

    @pytest.mark.asyncio
    async def test_list_empty_returns_friendly_message(
        self, list_tool: TaskListTool, ctx: ToolContext
    ) -> None:
        result = await list_tool.execute({}, ctx)
        assert result == "No tasks yet."

    @pytest.mark.asyncio
    async def test_list_shows_all_with_blocked_by_count(
        self, list_tool: TaskListTool, ctx: ToolContext, workspace: Path
    ) -> None:
        a = Task(id="task_a", subject="Alpha", activeForm="Doing alpha")
        b = Task(
            id="task_b",
            subject="Beta",
            activeForm="Doing beta",
            status="in_progress",
            owner="agent",
            blockedBy=["task_a"],
        )
        c = Task(
            id="task_c",
            subject="Gamma",
            activeForm="Doing gamma",
            status="completed",
        )
        for t in (a, b, c):
            _save_task(workspace, t)

        result = await list_tool.execute({}, ctx)
        # 包含三任务的关键信息
        assert "Alpha" in result and "Beta" in result and "Gamma" in result
        assert "[pending]" in result
        assert "[in_progress]" in result and "agent" in result
        assert "[completed]" in result
        assert "blockedBy: 1" in result  # B 有 1 个上游

    @pytest.mark.asyncio
    async def test_list_filters_by_status(
        self, list_tool: TaskListTool, ctx: ToolContext, workspace: Path
    ) -> None:
        a = Task(id="task_a", subject="Alpha", activeForm="Doing alpha")
        b = Task(
            id="task_b",
            subject="Beta",
            activeForm="Doing beta",
            status="completed",
        )
        for t in (a, b):
            _save_task(workspace, t)

        result = await list_tool.execute({"status": "pending"}, ctx)
        assert "Alpha" in result
        assert "Beta" not in result

    @pytest.mark.asyncio
    async def test_list_skips_corrupted_files(
        self, list_tool: TaskListTool, ctx: ToolContext, workspace: Path
    ) -> None:
        a = Task(id="task_good", subject="Good", activeForm="Doing good")
        _save_task(workspace, a)
        # 写一个非法 JSON 文件
        (_tasks_dir(workspace) / "task_corrupt.json").write_text(
            "this is not json", encoding="utf-8"
        )

        result = await list_tool.execute({}, ctx)
        # 不崩,只返回 good
        assert "Good" in result
        assert "task_corrupt" not in result


# ==== task_update 状态机 ====


class TestUpdateStateMachine:
    @pytest.fixture()
    def update_tool(self) -> TaskUpdateTool:
        return TaskUpdateTool()

    @staticmethod
    def _seed(workspace: Path, **overrides: Any) -> Task:
        defaults = {
            "id": "task_a",
            "subject": "A",
            "activeForm": "Doing A",
            "status": "pending",
            "owner": None,
            "description": "",
            "blockedBy": [],
        }
        defaults.update(overrides)
        task = Task(**defaults)
        _save_task(workspace, task)
        return task

    @pytest.mark.asyncio
    async def test_update_pending_to_in_progress_auto_owner(
        self, update_tool: TaskUpdateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        self._seed(workspace)
        result = await update_tool.execute(
            {"taskId": "task_a", "status": "in_progress"}, ctx
        )
        assert "in_progress" in result
        loaded = _load_task(workspace, "task_a")
        assert loaded is not None
        assert loaded.status == "in_progress"
        # auto-fill: ctx.user_id 是 UUID,转 str
        assert loaded.owner == str(ctx.user_id)

    @pytest.mark.asyncio
    async def test_update_pending_to_in_progress_explicit_owner(
        self, update_tool: TaskUpdateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        self._seed(workspace)
        await update_tool.execute(
            {"taskId": "task_a", "status": "in_progress", "owner": "alice"}, ctx
        )
        loaded = _load_task(workspace, "task_a")
        assert loaded is not None
        assert loaded.owner == "alice"

    @pytest.mark.asyncio
    async def test_update_pending_to_in_progress_blocked_by_unfinished(
        self, update_tool: TaskUpdateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        self._seed(workspace, id="task_dep", subject="dep")  # pending
        self._seed(workspace, id="task_b", subject="B", blockedBy=["task_dep"])

        result = await update_tool.execute(
            {"taskId": "task_b", "status": "in_progress"}, ctx
        )
        assert "Error" in result and "task_dep" in result
        loaded = _load_task(workspace, "task_b")
        assert loaded is not None and loaded.status == "pending"

    @pytest.mark.asyncio
    async def test_update_in_progress_to_completed_emits_unblocked(
        self, update_tool: TaskUpdateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        self._seed(workspace, id="task_a", status="in_progress", owner="alice")
        self._seed(workspace, id="task_b", subject="B", blockedBy=["task_a"])
        self._seed(
            workspace, id="task_c", subject="C", blockedBy=["task_a"]
        )

        result = await update_tool.execute(
            {"taskId": "task_a", "status": "completed"}, ctx
        )
        assert "completed" in result
        assert "Unblocked" in result
        assert "task_b" in result and "task_c" in result

    @pytest.mark.asyncio
    async def test_update_completed_is_terminal(
        self, update_tool: TaskUpdateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        self._seed(workspace, status="completed")
        result = await update_tool.execute(
            {"taskId": "task_a", "status": "in_progress"}, ctx
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_update_in_progress_to_pending_clears_owner(
        self, update_tool: TaskUpdateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        self._seed(workspace, status="in_progress", owner="alice")
        await update_tool.execute(
            {"taskId": "task_a", "status": "pending"}, ctx
        )
        loaded = _load_task(workspace, "task_a")
        assert loaded is not None
        assert loaded.status == "pending"
        assert loaded.owner is None


# ==== task_update 依赖 patch ====


class TestUpdateDependencyPatch:
    @pytest.fixture()
    def update_tool(self) -> TaskUpdateTool:
        return TaskUpdateTool()

    @pytest.mark.asyncio
    async def test_update_add_blocked_by_unknown_rejected(
        self, update_tool: TaskUpdateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        TestUpdateStateMachine._seed(workspace)
        result = await update_tool.execute(
            {"taskId": "task_a", "addBlockedBy": ["task_missing"]}, ctx
        )
        assert "Error" in result and "task_missing" in result

    @pytest.mark.asyncio
    async def test_update_remove_blocked_by_works(
        self, update_tool: TaskUpdateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        TestUpdateStateMachine._seed(workspace, id="task_dep", subject="dep")
        TestUpdateStateMachine._seed(
            workspace, id="task_b", subject="B", blockedBy=["task_dep"]
        )

        await update_tool.execute(
            {"taskId": "task_b", "removeBlockedBy": ["task_dep"]}, ctx
        )
        loaded = _load_task(workspace, "task_b")
        assert loaded is not None and loaded.blockedBy == []

        # 现在 B 应该可以启动了
        ok, _ = _can_start(workspace, loaded)
        assert ok

    @pytest.mark.asyncio
    async def test_update_remove_unknown_blocked_by_is_noop(
        self, update_tool: TaskUpdateTool, ctx: ToolContext, workspace: Path
    ) -> None:
        TestUpdateStateMachine._seed(workspace)
        result = await update_tool.execute(
            {"taskId": "task_a", "removeBlockedBy": ["task_never_was_dep"]}, ctx
        )
        # 不报错,任务原样
        assert "Error" not in result
        loaded = _load_task(workspace, "task_a")
        assert loaded is not None and loaded.blockedBy == []


# ==== 循环检测 ====


class TestCycleDetection:
    @pytest.fixture()
    def update_tool(self) -> TaskUpdateTool:
        return TaskUpdateTool()

    @pytest.fixture()
    def create_tool(self) -> TaskCreateTool:
        return TaskCreateTool()

    @pytest.mark.asyncio
    async def test_detect_simple_self_loop(
        self, create_tool: TaskCreateTool, update_tool: TaskUpdateTool, ctx: ToolContext
    ) -> None:
        # 先建 A,然后 update A 加 blockedBy=[A] -> 自环
        a = await create_tool.execute(
            {"subject": "A", "activeForm": "A"}, ctx
        )
        a_id = a.split()[1].rstrip(":")
        result = await update_tool.execute(
            {"taskId": a_id, "addBlockedBy": [a_id]}, ctx
        )
        assert "Error" in result and "cycle" in result.lower()

    @pytest.mark.asyncio
    async def test_detect_two_node_cycle(
        self, create_tool: TaskCreateTool, update_tool: TaskUpdateTool, ctx: ToolContext
    ) -> None:
        a = (await create_tool.execute(
            {"subject": "A", "activeForm": "A"}, ctx
        )).split()[1].rstrip(":")
        b = (await create_tool.execute(
            {"subject": "B", "activeForm": "B", "blockedBy": [a]}, ctx
        )).split()[1].rstrip(":")
        # A 加 blockedBy=[B] → A→B→A
        result = await update_tool.execute(
            {"taskId": a, "addBlockedBy": [b]}, ctx
        )
        assert "Error" in result and "cycle" in result.lower()
        assert a in result and b in result

    @pytest.mark.asyncio
    async def test_detect_three_node_cycle(
        self, create_tool: TaskCreateTool, update_tool: TaskUpdateTool, ctx: ToolContext
    ) -> None:
        a = (await create_tool.execute(
            {"subject": "A", "activeForm": "A"}, ctx
        )).split()[1].rstrip(":")
        b = (await create_tool.execute(
            {"subject": "B", "activeForm": "B", "blockedBy": [a]}, ctx
        )).split()[1].rstrip(":")
        c = (await create_tool.execute(
            {"subject": "C", "activeForm": "C", "blockedBy": [b]}, ctx
        )).split()[1].rstrip(":")
        # A 加 blockedBy=[C] → A→C→B→A
        result = await update_tool.execute(
            {"taskId": a, "addBlockedBy": [c]}, ctx
        )
        assert "Error" in result and "cycle" in result.lower()


# ==== _unblocked_after ====


class TestUnblockedAfter:
    def test_unblocked_after_returns_only_now_unblocked(
        self, workspace: Path
    ) -> None:
        # A → B (B blocked by A only) → 完成 A 后 B 解锁
        # A,X → C (C blocked by both A and X) → 完成 A 后 C 仍然 blocked(X 未完成)
        a = Task(id="task_a", subject="A", activeForm="A", status="completed")
        x = Task(id="task_x", subject="X", activeForm="X", status="pending")
        b = Task(
            id="task_b", subject="B", activeForm="B", blockedBy=["task_a"]
        )
        c = Task(
            id="task_c",
            subject="C",
            activeForm="C",
            blockedBy=["task_a", "task_x"],
        )
        for t in (a, x, b, c):
            _save_task(workspace, t)

        unblocked = _unblocked_after(workspace, "task_a")
        ids = {t.id for t in unblocked}
        assert ids == {"task_b"}  # 只有 B,不包含 C(还有 X 未完成)
