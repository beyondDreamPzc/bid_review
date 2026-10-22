"""Frozen schema for collaboration, assistant review and source conversion."""
from alembic import op
import sqlalchemy as sa

revision = "0008_delivery"
down_revision = "0007_retrieval"
branch_labels = None
depends_on = None

def upgrade():
    for table,column in (("users","disabled"),("requirements","retired"),("review_issues","withdrawn")):
        op.add_column(table,sa.Column(column,sa.Boolean(),nullable=False,server_default=sa.false()))
    with op.batch_alter_table("jobs") as batch:
        batch.alter_column("revision_id",existing_type=sa.String(36),nullable=True)
    op.create_table('notifications',
        sa.Column('id',sa.String(length=36),primary_key=True),
        sa.Column('project_id',sa.String(length=36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('user_id',sa.String(length=36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('title',sa.String(length=200),nullable=False),
        sa.Column('section',sa.String(length=30),nullable=False),
        sa.Column('read_at',sa.DateTime(),nullable=True),
        sa.Column('created_at',sa.DateTime(),nullable=False))
    op.create_index('ix_notifications_user_id','notifications',['user_id'])
    op.create_index('ix_notifications_project_id','notifications',['project_id'])
    op.create_table('change_impacts',
        sa.Column('id',sa.String(length=36),primary_key=True),
        sa.Column('project_id',sa.String(length=36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('requirement_id',sa.String(length=36),sa.ForeignKey('requirements.id'),nullable=False),
        sa.Column('source',sa.JSON(),nullable=False),
        sa.Column('note',sa.Text(),nullable=False),
        sa.Column('disposition',sa.String(length=20),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),
        sa.Column('created_by',sa.String(length=36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('reviewed_by',sa.String(length=36),sa.ForeignKey('users.id'),nullable=True),
        sa.Column('review_note',sa.Text(),nullable=True),
        sa.Column('created_at',sa.DateTime(),nullable=False))
    op.create_index('ix_change_impacts_requirement_id','change_impacts',['requirement_id'])
    op.create_index('ix_change_impacts_project_id','change_impacts',['project_id'])
    op.create_table('document_conversions',
        sa.Column('id',sa.String(length=36),primary_key=True),
        sa.Column('project_id',sa.String(length=36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('document_id',sa.String(length=36),sa.ForeignKey('documents.id'),nullable=True),
        sa.Column('revision_id',sa.String(length=36),sa.ForeignKey('document_revisions.id'),nullable=True),
        sa.Column('job_id',sa.String(length=36),sa.ForeignKey('jobs.id'),nullable=True,unique=True),
        sa.Column('title',sa.String(length=200),nullable=False),
        sa.Column('kind',sa.String(length=20),nullable=False),
        sa.Column('raw_key',sa.String(length=300),nullable=False),
        sa.Column('raw_hash',sa.String(length=64),nullable=False),
        sa.Column('runtime',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(length=36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False))
    op.create_index('ix_document_conversions_project_id','document_conversions',['project_id'])
    op.create_table('assistant_runs',
        sa.Column('id',sa.String(length=36),primary_key=True),
        sa.Column('project_id',sa.String(length=36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('job_id',sa.String(length=36),sa.ForeignKey('jobs.id'),nullable=False,unique=True),
        sa.Column('index_id',sa.String(length=36),sa.ForeignKey('retrieval_indexes.id'),nullable=False),
        sa.Column('epoch',sa.Integer(),nullable=False),
        sa.Column('material_set_id',sa.String(length=36),sa.ForeignKey('material_sets.id'),nullable=False),
        sa.Column('baseline_id',sa.String(length=36),sa.ForeignKey('baselines.id'),nullable=True),
        sa.Column('requirement_revision_id',sa.String(length=36),sa.ForeignKey('requirement_revisions.id'),nullable=True),
        sa.Column('review_version',sa.Integer(),nullable=True),
        sa.Column('kind',sa.String(length=20),nullable=False),
        sa.Column('question',sa.Text(),nullable=False),
        sa.Column('sources',sa.JSON(),nullable=False),
        sa.Column('result',sa.JSON(),nullable=False),
        sa.Column('model_profile',sa.JSON(),nullable=False),
        sa.Column('created_by',sa.String(length=36),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False))
    op.create_index('ix_assistant_runs_project_id','assistant_runs',['project_id'])

def downgrade():
    if op.get_bind().execute(sa.text("SELECT COUNT(*) FROM jobs WHERE revision_id IS NULL")).scalar():
        raise RuntimeError("Retain conversion/assistant jobs; do not downgrade while null-revision jobs exist")
    for table in ("assistant_runs","document_conversions","change_impacts","notifications"):
        op.drop_table(table)
    with op.batch_alter_table("jobs") as batch:
        batch.alter_column("revision_id",existing_type=sa.String(36),nullable=False)
    for table,column in (("review_issues","withdrawn"),("requirements","retired"),("users","disabled")):
        op.drop_column(table,column)
