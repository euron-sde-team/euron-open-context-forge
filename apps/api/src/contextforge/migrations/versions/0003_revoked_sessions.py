"""revoked sessions in postgres

Revision ID: 8d41f0c27a65 (file name 0003)
Revises: 3b7c2e91d4a0
Create Date: 2026-10-26 15:00:00

Signed-out session ids move out of the evictable cache into Postgres, so memory pressure
on Redis (or the in-process LRU) can never revive a signed-out session.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8d41f0c27a65"
down_revision: Union[str, Sequence[str], None] = "3b7c2e91d4a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revoked_sessions",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index(
        op.f("ix_revoked_sessions_expires_at"), "revoked_sessions", ["expires_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_revoked_sessions_expires_at"), table_name="revoked_sessions")
    op.drop_table("revoked_sessions")
