"""conversation agent and ACP session, message details

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("agent", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column("session_id", sa.Text(), nullable=True))
    op.add_column(
        "messages",
        sa.Column(
            "details",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "details")
    op.drop_column("conversations", "session_id")
    op.drop_column("conversations", "agent")
