import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (AuditEvent, Document, DocumentRevision, IdempotencyRecord, Job,
                        OutboxEvent, Project, ProjectMember, User)
from app.storage import BlobStore, sha256
from app.parsers import PROFILE, PARSE_JOB_KINDS


def project_access(db: Session, project_id: str, user: User, write: bool = False) -> Project:
    membership = db.get(ProjectMember, (project_id, user.id))
    if membership is None:
        raise HTTPException(404, "Project not found")
    if write and membership.role not in {"OWNER", "EDITOR"}:
        raise HTTPException(403, "Write access required")
    return db.get(Project, project_id)


def ingest_pdf(db: Session, store: BlobStore, user: User, project_id: str,
               content: bytes, title: str, kind: str, key: str, profile: str,
               document_id: str | None = None, source_url: str | None = None) -> dict:
    # Lock a shared parent before checking the idempotency key/revision counter.
    # Locking reads also avoid a stale MySQL REPEATABLE READ snapshot.
    db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    content_hash = sha256(content)
    scope = f"{user.id}:{project_id}:{document_id or 'new-document'}"
    request_hash = sha256(json.dumps({"sha256": content_hash, "title": title, "kind": kind,
                                     "source_url": source_url}, sort_keys=True).encode())
    prior = db.scalar(select(IdempotencyRecord).where(
        IdempotencyRecord.scope == scope, IdempotencyRecord.key == key).with_for_update())
    if prior:
        if prior.request_hash != request_hash:
            raise HTTPException(409, "Idempotency key was already used for a different request")
        response = prior.response
        db.commit()  # Release the parent/idempotency row locks before returning.
        return response
    if document_id:
        document = db.scalar(select(Document).where(Document.id == document_id,
                             Document.project_id == project_id).with_for_update())
        if document is None:
            raise HTTPException(404, "Document not found")
        prior_revision = db.scalar(select(DocumentRevision).where(
            DocumentRevision.document_id == document_id,
            DocumentRevision.sha256 == content_hash).with_for_update())
        if prior_revision:
            job = db.scalar(select(Job).where(Job.revision_id == prior_revision.id, Job.kind.in_(PARSE_JOB_KINDS))
                            .order_by(Job.created_at.desc(), Job.id).limit(1))
            result = {"document_id": document.id, "revision_id": prior_revision.id,
                      "revision_no": prior_revision.revision_no, "job_id": job.id,
                      "sha256": content_hash, "reused": True}
            db.add(IdempotencyRecord(scope=scope, key=key, request_hash=request_hash, response=result))
            db.commit()
            return result
        latest = db.scalar(select(DocumentRevision).where(
            DocumentRevision.document_id == document_id).order_by(
                DocumentRevision.revision_no.desc()).limit(1).with_for_update())
        revision_no = latest.revision_no + 1 if latest else 1
    else:
        document = Document(project_id=project_id, title=title, kind=kind)
        db.add(document)
        db.flush()
        revision_no = 1
    storage_key = f"projects/{project_id}/originals/{content_hash}.pdf"
    store.put(storage_key, content)
    revision = DocumentRevision(document_id=document.id, revision_no=revision_no,
                                sha256=content_hash, storage_key=storage_key,
                                byte_size=len(content), uploaded_by=user.id, source_url=source_url)
    db.add(revision)
    db.flush()
    job = Job(project_id=project_id, revision_id=revision.id,kind="PDF_TEXT_PROBE" if profile==PROFILE else "PDF_PARSE",
              dedup_key=f"parse:{revision.id}:{profile}", parser_profile=profile)
    db.add(job)
    db.flush()
    result = {"document_id": document.id, "revision_id": revision.id,
              "revision_no": revision_no, "job_id": job.id, "sha256": content_hash, "reused": False}
    db.add_all([
        OutboxEvent(job_id=job.id),
        IdempotencyRecord(scope=scope, key=key, request_hash=request_hash, response=result),
        AuditEvent(project_id=project_id, actor_id=user.id, action="DOCUMENT_REVISION_CREATED",
                   object_id=revision.id, details={"sha256": content_hash, "job_id": job.id}),
    ])
    db.commit()
    return result
