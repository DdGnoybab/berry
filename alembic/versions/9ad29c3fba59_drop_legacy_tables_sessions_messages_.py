"""drop legacy tables (sessions, messages, goals, milestones, materials, attempts)

Revision ID: 9ad29c3fba59
Revises: 6b4faa0ba1ee
Create Date: 2026-05-31 11:09:52.266326+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '9ad29c3fba59'
down_revision: Union[str, None] = '6b4faa0ba1ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # goals <-> milestones 存在循环 FK:
    #   goals.current_milestone_id -> milestones  (use_alter=True)
    #   milestones.goal_id -> goals
    # 必须先手动 drop 循环 FK,才能按依赖顺序 drop 表
    op.drop_constraint('goals_current_milestone_id_fkey', 'goals', type_='foreignkey')

    # 删除顺序:从最叶子开始,避免 FK 约束阻拦
    op.drop_table('attempts')
    op.drop_table('materials')
    op.drop_table('milestones')
    op.drop_table('goals')
    op.drop_table('messages')
    op.drop_table('llm_call_logs')   # 后面 0.5 重建,加新字段
    op.drop_table('sessions')
    op.drop_table('users')           # 也 drop,0.5 用新 schema 重建


def downgrade() -> None:
    # 不可逆:旧表里数据没保留价值,downgrade 只重建空 schema 占位
    raise NotImplementedError(
        "drop_legacy_tables is one-way; restore via fresh init migration if needed"
    )
