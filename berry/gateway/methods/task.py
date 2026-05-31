"""task.* handlers (Stage 1 stub: returns empty list / not found)."""

from __future__ import annotations

from berry.gateway.methods.registry import CallContext, MethodRegistry
from berry.protocol.errors import ErrorCode, ProtocolError
from berry.protocol.methods_core import (
    CORE_METHODS,
    TaskCancelParams,
    TaskDetailParams,
    TaskListParams,
)
from berry.protocol.types import Page, TaskInfo


async def list_tasks(
    params: TaskListParams, ctx: CallContext
) -> Page[TaskInfo]:
    return Page[TaskInfo](items=[], next_cursor=None)


async def detail(
    params: TaskDetailParams, ctx: CallContext
) -> TaskInfo:
    raise ProtocolError(
        ErrorCode.TASK_NOT_FOUND, f"task {params.task_id} not found"
    )


async def cancel(
    params: TaskCancelParams, ctx: CallContext
) -> TaskInfo:
    raise ProtocolError(
        ErrorCode.TASK_NOT_FOUND, f"task {params.task_id} not found"
    )


def register(registry: MethodRegistry) -> None:
    registry.register(CORE_METHODS["task.list"], list_tasks)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["task.detail"], detail)  # type: ignore[arg-type]
    registry.register(CORE_METHODS["task.cancel"], cancel)  # type: ignore[arg-type]
