"""Frozen material retrieval indexes and source chunks."""
from alembic import op
import sqlalchemy as sa

revision = "0007_retrieval"
down_revision = "0006_requirement_extraction"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("retrieval_indexes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("material_set_id", sa.String(36), sa.ForeignKey("material_sets.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("profile", sa.String(100), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("published_token", sa.Integer()),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("material_set_id", "profile", name="uq_retrieval_material_profile"))
    op.create_index("ix_retrieval_indexes_project_id", "retrieval_indexes", ["project_id"])
    op.create_table("retrieval_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("index_id", sa.String(36), sa.ForeignKey("retrieval_indexes.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False), sa.Column("source", sa.JSON(), nullable=False))
    op.create_index("ix_retrieval_chunks_index_id", "retrieval_chunks", ["index_id"])


def downgrade():
    op.drop_table("retrieval_chunks")
    op.drop_table("retrieval_indexes")
