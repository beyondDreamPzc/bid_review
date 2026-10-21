"""Append-only page extraction quality reviews."""
from alembic import op
import sqlalchemy as sa

revision = "0005_page_quality"
down_revision = "0004_web_session"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("page_quality_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("parse_artifacts.id"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("diagnostic_profile", sa.String(80), nullable=False),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("artifact_id", "page", "version", name="uq_page_quality_version"))
    op.create_index("ix_page_quality_reviews_project_id", "page_quality_reviews", ["project_id"])
    op.create_index("ix_page_quality_reviews_artifact_id", "page_quality_reviews", ["artifact_id"])


def downgrade():
    op.drop_index("ix_page_quality_reviews_artifact_id", table_name="page_quality_reviews")
    op.drop_index("ix_page_quality_reviews_project_id", table_name="page_quality_reviews")
    op.drop_table("page_quality_reviews")
