"""Isolated browser demo sessions, never production API credentials."""
from alembic import op
import sqlalchemy as sa

revision = "0003_demo_workspace"
down_revision = "0002_human_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("demo_workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("editor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("demo_workspaces")
