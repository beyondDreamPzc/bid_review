import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, utcnow


def uid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    review_epoch: Mapped[int] = mapped_column(Integer, default=0)
    current_baseline_id: Mapped[str | None] = mapped_column(String(36))
    current_material_set_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="OWNER")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentRevision(Base):
    __tablename__ = "document_revisions"
    __table_args__ = (
        UniqueConstraint("document_id", "revision_no", name="uq_doc_revision"),
        UniqueConstraint("document_id", "sha256", name="uq_doc_content"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(300))
    byte_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="UPLOADED")
    source_url: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ParseArtifact(Base):
    __tablename__ = "parse_artifacts"
    __table_args__ = (UniqueConstraint("revision_id", "parser_profile", name="uq_parse_profile"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    revision_id: Mapped[str] = mapped_column(ForeignKey("document_revisions.id"), index=True)
    parser_profile: Mapped[str] = mapped_column(String(100))
    page_count: Mapped[int] = mapped_column(Integer)
    block_count: Mapped[int] = mapped_column(Integer)
    quality_status: Mapped[str] = mapped_column(String(32))
    quality_flags: Mapped[list] = mapped_column(JSON)
    storage_key: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    artifact_id: Mapped[str] = mapped_column(ForeignKey("parse_artifacts.id"), primary_key=True)
    block_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    page: Mapped[int] = mapped_column(Integer)
    bbox: Mapped[list] = mapped_column(JSON)
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64))


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("dedup_key", name="uq_job_dedup"),
        Index("ix_jobs_due", "status", "next_attempt_at"),
        Index("ix_jobs_lease", "status", "lease_until"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("document_revisions.id"))
    kind: Mapped[str] = mapped_column(String(30), default="PDF_TEXT_PROBE")
    dedup_key: Mapped[str] = mapped_column(String(200))
    parser_profile: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="QUEUED")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_dispatched_at: Mapped[datetime | None] = mapped_column(DateTime)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("parse_artifacts.id"))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    claim_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    scope: Mapped[str] = mapped_column(String(180), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    object_id: Mapped[str] = mapped_column(String(36))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Requirement(Base):
    __tablename__ = "requirements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    review_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RequirementRevision(Base):
    __tablename__ = "requirement_revisions"
    __table_args__ = (UniqueConstraint("requirement_id", "revision_no", name="uq_requirement_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(20))
    sources: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Baseline(Base):
    __tablename__ = "baselines"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_baseline_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("baselines.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BaselineItem(Base):
    __tablename__ = "baseline_items"
    baseline_id: Mapped[str] = mapped_column(ForeignKey("baselines.id"), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"), primary_key=True)
    requirement_revision_id: Mapped[str] = mapped_column(ForeignKey("requirement_revisions.id"))


class MaterialSet(Base):
    __tablename__ = "material_sets"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_material_set_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    items: Mapped[list] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReviewIssue(Base):
    __tablename__ = "review_issues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"), index=True)
    requirement_revision_id: Mapped[str] = mapped_column(ForeignKey("requirement_revisions.id"))
    baseline_id: Mapped[str] = mapped_column(ForeignKey("baselines.id"))
    material_set_id: Mapped[str] = mapped_column(ForeignKey("material_sets.id"))
    epoch: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20))
    evidence: Mapped[list] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkItem(Base):
    __tablename__ = "work_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    issue_id: Mapped[str] = mapped_column(ForeignKey("review_issues.id"), unique=True)
    assignee_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="TODO")
    version: Mapped[int] = mapped_column(Integer, default=1)
    current_submission_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaskSubmission(Base):
    __tablename__ = "task_submissions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True)
    task_version: Mapped[int] = mapped_column(Integer)
    requirement_revision_id: Mapped[str] = mapped_column(ForeignKey("requirement_revisions.id"))
    baseline_id: Mapped[str] = mapped_column(ForeignKey("baselines.id"))
    material_set_id: Mapped[str] = mapped_column(ForeignKey("material_sets.id"))
    epoch: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON)
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaskDecision(Base):
    __tablename__ = "task_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), index=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("task_submissions.id"))
    task_version: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RequirementDecision(Base):
    __tablename__ = "requirement_decisions"
    __table_args__ = (UniqueConstraint("requirement_id", "sequence", name="uq_requirement_decision_seq"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    requirement_id: Mapped[str] = mapped_column(ForeignKey("requirements.id"), index=True)
    requirement_revision_id: Mapped[str] = mapped_column(ForeignKey("requirement_revisions.id"))
    baseline_id: Mapped[str] = mapped_column(ForeignKey("baselines.id"))
    material_set_id: Mapped[str] = mapped_column(ForeignKey("material_sets.id"))
    epoch: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    review_version: Mapped[int] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON)
    decided_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DemoWorkspace(Base):
    """仅供本机产品体验；凭据只允许操作自身隔离的构造数据。"""
    __tablename__ = "demo_workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), unique=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    editor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    context: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
