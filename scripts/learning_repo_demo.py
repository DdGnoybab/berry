"""Round 1 学习助手 repo 层手动演示。

跑法:
    uv run python scripts/learning_repo_demo.py

这个脚本不是测试,是**给你看 Round 1 唯一能演示的东西**:
1. 创建一个学习目标(Goal)
2. 给它拆 4 个里程碑(Milestone)
3. 用 reorder 把第 4 个 milestone(interrupt)提前到第 2 位
4. 验证 reorder 二阶段事务真的工作(不撞 UniqueConstraint)
5. 给第一个 milestone 创建一道答题(Attempt),走完 set_answer → set_score → set_decision

Round 2 之前没有 LLM、没有工具、没有审批,所以这是 Round 1 唯一能直接玩的东西。

跑完 dev DB 会有一条 demo 记录,想清掉:
    psql berry -c "DELETE FROM goals WHERE workspace_path LIKE '%demo-langgraph';"

会顺便清掉所有关联的 milestones / materials / attempts(FK CASCADE)。
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from berry.assistants.learning.repos.attempt_repo import AttemptRepo
from berry.assistants.learning.repos.goal_repo import GoalRepo
from berry.assistants.learning.repos.milestone_repo import MilestoneRepo
from berry.config import settings
from berry.core.db.repos.user_repo import UserRepo


async def main() -> None:
    engine = create_async_engine(settings.database_url_async)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as db:
        # ── 1. 准备一个用户 ──
        user = await UserRepo(db).create_or_get_by_external(
            external_source="cli",
            external_id="demo_user",
            display_name="Demo User",
        )
        print(f"✓ user {user.id} ({user.display_name})")

        # ── 2. 创建一个学习目标 ──
        goal = await GoalRepo(db).create(
            user_id=user.id,
            title="学 LangGraph",
            workspace_path=f"goals/{user.id}/demo-langgraph",
        )
        print(f"\n✓ goal {goal.id}")
        print(f"  title       : {goal.title}")
        print(f"  status      : {goal.status}")
        print(f"  workspace   : {goal.workspace_path}")

        # ── 3. 拆 4 个 milestone ──
        ms = await MilestoneRepo(db).insert_batch(
            goal.id,
            [
                ("理解 StateGraph", "节点 + 边 + 状态 + 编译"),
                ("Conditional Edges", "条件路由"),
                ("Checkpointer", "持久化 + resume"),
                ("Interrupt", "Human-in-the-loop 审批"),
            ],
        )
        print(f"\n✓ {len(ms)} 个 milestone 拆好(初始顺序):")
        for m in ms:
            print(f"  {m.order_index}. {m.name:25s} [{m.status}]")

        # ── 4. 重排:把 Interrupt(原 #3)提到 #1,验证 reorder 二阶段事务 ──
        new_order = [ms[0].id, ms[3].id, ms[1].id, ms[2].id]
        await MilestoneRepo(db).reorder(goal.id, new_order)

        after = await MilestoneRepo(db).list_by_goal(goal.id)
        print("\n✓ reorder 完成(把 Interrupt 从 #3 提到 #1):")
        for m in after:
            print(f"  {m.order_index}. {m.name:25s} [{m.status}]")

        # ── 5. 走一个 milestone 的答题完整流程 ──
        focus = after[0]  # 第 0 个,「理解 StateGraph」
        print(f"\n✓ 给 milestone '{focus.name}' 出一道题:")

        attempt = await AttemptRepo(db).create(
            milestone_id=focus.id,
            kind="application",
            question="用一句话解释 StateGraph 跟普通有向图的区别。",
        )
        print(f"  题目        : {attempt.question}")
        print(f"  attempt id  : {attempt.id}")

        # 用户答了
        await AttemptRepo(db).set_answer(
            attempt.id,
            "StateGraph 在每条边触发时把整个 state 沿着边传递,节点能读 + 改 state,"
            "这跟普通有向图『只传控制流不传数据』不一样。",
        )

        # Agent 评分(Round 4 才会真做这步,这里手填演示)
        await AttemptRepo(db).set_score(
            attempt.id,
            score=4,
            reasoning="抓到了核心:state 沿边传递、节点可读写。差一步:没提到 reducer 这种合并 state 的机制。",
            reference_points=[
                "state 沿边传递(普通有向图只传控制)",
                "节点可读 + 改 state",
                "reducer 合并多支路 state 更新",
            ],
        )

        # 用户决定 next
        await AttemptRepo(db).set_decision(attempt.id, "next")

        # ── 6. 看最终状态 ──
        finished = await AttemptRepo(db).get_by_id(attempt.id)
        assert finished is not None
        print("\n✓ attempt 完整生命周期走完:")
        print(f"  score       : {finished.score}/5")
        print(f"  reasoning   : {finished.reasoning}")
        print(f"  reference   :")
        for p in finished.reference_points or []:
            print(f"    - {p}")
        print(f"  user_decision : {finished.user_decision}")

        print(f"\n✓ goal id = {goal.id}")
        print(
            "  清理:psql berry -c \"DELETE FROM goals "
            "WHERE workspace_path LIKE '%demo-langgraph';\""
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
