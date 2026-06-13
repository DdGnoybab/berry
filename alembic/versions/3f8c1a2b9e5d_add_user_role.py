"""add user.role for admin gating

Revision ID: 3f8c1a2b9e5d
Revises: 4c2b7e9f1a3d
Create Date: 2026-06-13 10:00:00.000000+00:00

User 表加 role 字段(`'user'` / `'admin'`),用于 /v1/admin/* 路由鉴权。
默认全部老用户是 `'user'`,seed 时把 handle='default'(CLI 默认用户) 升成 admin —
那是单用户 dogfood 阶段唯一存在的账号,升它最不容易误伤。

Web 注册用户(handle 形如 `web:<username>`)默认 'user',要哪个升 admin
之后用 SQL 显式 UPDATE,不在迁移里硬编码。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f8c1a2b9e5d"
down_revision: Union[str, None] = "4c2b7e9f1a3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 加列,server_default 'user' 保证既有行不为 NULL。
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(),
            nullable=False,
            server_default=sa.text("'user'"),
        ),
    )
    # seed:CLI 默认用户升 admin。dogfood 阶段唯一存在的账号。
    op.execute("UPDATE users SET role = 'admin' WHERE handle = 'default'")


def downgrade() -> None:
    op.drop_column("users", "role")
