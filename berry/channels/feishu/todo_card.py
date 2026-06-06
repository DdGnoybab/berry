"""飞书 Todo 卡片渲染器 — 把 todo 列表渲染成飞书 Markdown。

通用渲染,不区分业务场景(学习/工作/穿搭都一样显示)。
对齐 openclaw card 渲染风格:简洁、图标清晰。
"""

from __future__ import annotations


def render_todo_card(todos: list[dict[str, str]], old_todos: list[dict[str, str]] | None = None) -> str:
    """把 todo 列表渲染成飞书 Markdown 文本。

    Args:
        todos: 当前 todo 列表 [{content, activeForm, status}, ...]
        old_todos: 变更前的 todo 列表(用于 diff 渲染,暂未启用)

    Returns:
        飞书 Markdown 字符串,直接塞 send_card_markdown 的 markdown 参数。
    """
    if not todos:
        return "📋 任务清单已清空"

    total = len(todos)
    completed = sum(1 for t in todos if t["status"] == "completed")

    lines = [f"## 📋 任务进度 ({completed}/{total})"]

    for todo in todos:
        status = todo.get("status", "pending")
        content = todo.get("content", "")
        active_form = todo.get("activeForm", "")

        if status == "completed":
            lines.append(f"✅ ~~{content}~~")
        elif status == "in_progress":
            suffix = f" ← {active_form}" if active_form else ""
            lines.append(f"▸ **{content}**{suffix}")
        else:
            lines.append(f"○ {content}")

    return "\n".join(lines)
