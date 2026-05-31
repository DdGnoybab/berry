"""recreate core tables (users, projects, llm_call_logs)

Revision ID: 9f5d913298fa
Revises: 9ad29c3fba59
Create Date: 2026-05-31 11:10:07.168370+00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9f5d913298fa'
down_revision: Union[str, None] = '9ad29c3fba59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──
    op.create_table(
        'users',
        sa.Column(
            'id', sa.UUID(), nullable=False,
            server_default=sa.text('gen_random_uuid()')
        ),
        sa.Column('handle', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column(
            'metadata', postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}', nullable=False
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('handle', name='uq_users_handle'),
    )

    # ── projects ──
    op.create_table(
        'projects',
        sa.Column(
            'id', sa.UUID(), nullable=False,
            server_default=sa.text('gen_random_uuid()')
        ),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('domain', sa.String(), nullable=False),
        sa.Column('workspace_path', sa.String(), nullable=False),
        sa.Column(
            'metadata', postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}', nullable=False
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], ondelete='CASCADE',
            name='fk_projects_user_id',
        ),
        sa.UniqueConstraint('user_id', 'name', name='uq_projects_user_name'),
    )

    # ── llm_call_logs ──
    op.create_table(
        'llm_call_logs',
        sa.Column(
            'id', sa.UUID(), nullable=False,
            server_default=sa.text('gen_random_uuid()')
        ),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column(
            'request', postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            'response', postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            'metadata', postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}', nullable=False
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], ondelete='CASCADE',
            name='fk_llm_call_logs_user_id',
        ),
        sa.ForeignKeyConstraint(
            ['project_id'], ['projects.id'], ondelete='SET NULL',
            name='fk_llm_call_logs_project_id',
        ),
    )


def downgrade() -> None:
    op.drop_table('llm_call_logs')
    op.drop_table('projects')
    op.drop_table('users')
