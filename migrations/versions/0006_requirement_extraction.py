"""Model extraction runs and human-reviewed requirement candidates."""
from alembic import op
import sqlalchemy as sa

revision = "0006_requirement_extraction"
down_revision = "0005_page_quality"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("extraction_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("parse_artifacts.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("page_reviews", sa.JSON(), nullable=False), sa.Column("batches", sa.JSON(), nullable=False),
        sa.Column("model_config_snapshot", sa.JSON(), nullable=False),
        sa.Column("prompt_profile", sa.String(80), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("completed_at", sa.DateTime()))
    op.create_index("ix_extraction_runs_project_id", "extraction_runs", ["project_id"])
    op.create_index("ix_extraction_runs_artifact_id", "extraction_runs", ["artifact_id"])
    op.create_table("requirement_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("extraction_runs.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("proposed", sa.JSON(), nullable=False), sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("requirement_id", sa.String(36), sa.ForeignKey("requirements.id")),
        sa.Column("review", sa.JSON()), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "fingerprint", name="uq_candidate_fingerprint"))
    op.create_index("ix_requirement_candidates_run_id", "requirement_candidates", ["run_id"])
    op.create_index("ix_requirement_candidates_project_id", "requirement_candidates", ["project_id"])


def downgrade():
    op.drop_table("requirement_candidates")
    op.drop_table("extraction_runs")
