"""Revocable browser sessions for the real project workspace."""
from alembic import op
import sqlalchemy as sa

revision = "0004_web_session"
down_revision = "0003_demo_workspace"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("web_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_web_sessions_user_id", "web_sessions", ["user_id"])


def downgrade():
    op.drop_index("ix_web_sessions_user_id", table_name="web_sessions")
    op.drop_table("web_sessions")
