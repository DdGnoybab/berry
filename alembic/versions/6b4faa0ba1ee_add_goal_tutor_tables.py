"""add goal tutor tables

Revision ID: 6b4faa0ba1ee
Revises: 21a6c7ae1717
Create Date: 2026-05-30 08:19:03.127263+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6b4faa0ba1ee'
down_revision: Union[str, None] = '21a6c7ae1717'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE (manual edit): the goals.current_milestone_id FK is created via
    # op.create_foreign_key AFTER both tables exist. Putting use_alter=True
    # inside ForeignKeyConstraint(...) on op.create_table is silently dropped
    # by SQLAlchemy's CreateTable compiler — it only honors use_alter on the
    # MetaData.create_all() path, not alembic's op.create_table. Without this
    # split the column would be created but the FK constraint wouldn't be.
    # See CLAUDE.md §7 数据库.
    op.create_table('goals',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('domain', sa.String(), server_default='learning', nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default='drafting', nullable=False),
    sa.Column('workspace_path', sa.String(), nullable=False),
    sa.Column('current_milestone_id', sa.UUID(), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('milestones',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('goal_id', sa.UUID(), nullable=False),
    sa.Column('order_index', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('passed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('goal_id', 'order_index', name='uq_milestones_order')
    )
    op.create_table('attempts',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('milestone_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('question', sa.String(), nullable=False),
    sa.Column('choices', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('correct_index', sa.Integer(), nullable=True),
    sa.Column('user_answer', sa.String(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('reasoning', sa.String(), nullable=True),
    sa.Column('reference_points', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('user_decision', sa.String(), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('materials',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('milestone_id', sa.UUID(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('source_url', sa.String(), nullable=True),
    sa.Column('source_title', sa.String(), nullable=True),
    sa.Column('summary', sa.String(), nullable=True),
    sa.Column('size_bytes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('content_hash', sa.String(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['milestone_id'], ['milestones.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('milestone_id', 'filename', name='uq_materials_filename')
    )

    # Manual: add the goals.current_milestone_id FK now that milestones exists.
    # See note at top of upgrade() for why this is split out.
    op.create_foreign_key(
        'goals_current_milestone_id_fkey',
        'goals',
        'milestones',
        ['current_milestone_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    # Manual: drop the cross-table FK first so the tables can be dropped cleanly.
    op.drop_constraint('goals_current_milestone_id_fkey', 'goals', type_='foreignkey')

    op.drop_table('materials')
    op.drop_table('attempts')
    op.drop_table('milestones')
    op.drop_table('goals')
