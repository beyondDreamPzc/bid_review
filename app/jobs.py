import json
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from app.config import Settings
from app.database import utcnow
from app.models import (AuditEvent, DocumentBlock, DocumentRevision, Job, OutboxEvent,
                        ParseArtifact, uid)
from app.parsers import PARSE_JOB_KINDS, ParseRejected, parse_pdf
from app.storage import BlobStore, sha256


class StaleLease(RuntimeError):
    pass


@dataclass(frozen=True)
class Attempt:
    job_id: str
    project_id: str
    revision_id: str
    token: int
    storage_key: str
    original_hash: str
    parser_profile: str


def claim_job(factory, job_id: str, settings: Settings) -> Attempt | None:
    with factory.begin() as db:
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.kind not in PARSE_JOB_KINDS or job.status != "QUEUED" or job.next_attempt_at > utcnow():
            return None
        job.status = "RUNNING"
        job.attempt += 1
        job.lease_token += 1
        job.lease_until = utcnow() + timedelta(seconds=settings.lease_seconds)
        revision = db.get(DocumentRevision, job.revision_id)
        revision.status = "PARSING"
        return Attempt(job.id, job.project_id, revision.id, job.lease_token,
                       revision.storage_key, revision.sha256, job.parser_profile)


def owned_job(db, attempt: Attempt) -> Job:
    job = db.scalar(select(Job).where(Job.id == attempt.job_id).with_for_update())
    if (job is None or job.status != "RUNNING" or job.lease_token != attempt.token
            or job.lease_until is None or job.lease_until <= utcnow()):
        raise StaleLease("Task execution lease is no longer valid")
    return job


def heartbeat(factory, attempt: Attempt, settings: Settings):
    with factory.begin() as db:
        job = owned_job(db, attempt)
        job.lease_until = utcnow() + timedelta(seconds=settings.lease_seconds)


def persist_result(factory, attempt: Attempt, result: dict, store: BlobStore) -> str:
    if result["parser_profile"]!=attempt.parser_profile:
        raise ParseRejected("Parser result profile differs from the frozen task")
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
    artifact_hash = sha256(encoded)
    key = f"artifacts/{attempt.revision_id}/{artifact_hash}.json"
    store.put(key, encoded)
    with factory.begin() as db:
        job = owned_job(db, attempt)
        existing = db.scalar(select(ParseArtifact).where(
            ParseArtifact.revision_id == attempt.revision_id,
            ParseArtifact.parser_profile == attempt.parser_profile))
        if existing is None:
            artifact = ParseArtifact(revision_id=attempt.revision_id,
                                     parser_profile=attempt.parser_profile,
                                     page_count=result["page_count"], block_count=result["block_count"],
                                     quality_status=result["quality_status"],
                                     quality_flags=result["quality_flags"], storage_key=key,
                                     sha256=artifact_hash)
            db.add(artifact)
            db.flush()
            db.add_all(DocumentBlock(artifact_id=artifact.id, **block) for block in result["blocks"])
        else:
            artifact = existing
        job.status, job.artifact_id = "SUCCEEDED", artifact.id
        job.lease_until, job.error_code, job.error_detail = None, None, None
        db.get(DocumentRevision, attempt.revision_id).status = "NEEDS_REVIEW"
        db.add(AuditEvent(project_id=attempt.project_id, actor_id=None,
                          action="PDF_PARSE_COMPLETED", object_id=artifact.id,
                          details={"job_id": job.id, "profile": attempt.parser_profile,
                                   "quality_status": result["quality_status"]}))
        return artifact.id


def record_failure(factory, attempt: Attempt, settings: Settings, error: Exception):
    from app.mineru_parser import MinerUUnavailable
    with factory.begin() as db:
        job = owned_job(db, attempt)
        permanent = isinstance(error, (ParseRejected, FileNotFoundError))
        job.status = "FAILED" if permanent or job.attempt >= settings.job_max_attempts else "RETRY_WAIT"
        job.error_code = "PDF_REJECTED" if permanent else "PROCESSING_ERROR"
        # Do not expose absolute storage paths, tokens or raw document content.
        job.error_detail = str(error)[:300] if isinstance(error, ParseRejected) else type(error).__name__
        if isinstance(error,MinerUUnavailable):
            job.error_code="MINERU_RUNTIME_ERROR"
            job.error_detail=str(error)[:300]  # Only messages authored by our adapter, never SDK exception bodies.
        job.next_attempt_at = utcnow() + timedelta(seconds=min(60, 2 ** job.attempt))
        job.lease_until = None
        db.get(DocumentRevision, attempt.revision_id).status = "PARSE_FAILED" if job.status == "FAILED" else "RETRY_WAIT"


def run_job(factory, job_id: str, settings: Settings) -> dict:
    with factory() as db:
        job=db.get(Job,job_id)
        extraction=job is not None and job.kind=="REQUIREMENT_EXTRACTION"
        indexing=job is not None and job.kind=="MATERIAL_INDEX"
    if indexing:
        from app.retrieval import run_index
        return run_index(factory,job_id,settings)
    if extraction:
        from app.extraction_jobs import run_extraction
        return run_extraction(factory,job_id,settings)
    attempt = claim_job(factory, job_id, settings)
    if attempt is None:
        return {"status": "IGNORED"}
    try:
        store = BlobStore(settings.storage_path)
        data = store.read(attempt.storage_key)
        if sha256(data) != attempt.original_hash:
            raise ParseRejected("Original file integrity verification failed")
        result = parse_pdf(data, attempt.parser_profile, settings, lambda: heartbeat(factory, attempt, settings))
        heartbeat(factory, attempt, settings)
        artifact_id = persist_result(factory, attempt, result, store)
        return {"status": "SUCCEEDED", "artifact_id": artifact_id}
    except StaleLease:
        return {"status": "STALE_LEASE"}
    except Exception as error:
        try:
            record_failure(factory, attempt, settings, error)
        except StaleLease:
            return {"status": "STALE_LEASE"}
        return {"status": "FAILED_OR_RETRY_WAIT", "error_type": type(error).__name__}


def recover_jobs(factory, settings: Settings) -> int:
    """Rebuild dispatch intentions from MySQL, including lost Redis messages."""
    recovered = 0
    with factory.begin() as db:
        now = utcnow()
        # Bounded scans. A single dispatcher is used in the phase-1 deployment.
        jobs = db.scalars(select(Job).where(Job.status.in_(["QUEUED", "RUNNING", "RETRY_WAIT"]))
                          .order_by(Job.created_at).limit(500).with_for_update(skip_locked=True)).all()
        for job in jobs:
            if job.status == "RUNNING":
                if job.lease_until is None or job.lease_until > now:
                    continue
                job.lease_token += 1  # Immediately fence the old worker.
                job.lease_until = None
                job.status = "FAILED" if job.attempt >= settings.job_max_attempts else "RETRY_WAIT"
                job.error_code, job.error_detail = "LEASE_EXPIRED", "Worker lease expired"
                job.next_attempt_at = now
                if job.status == "FAILED" and job.kind in PARSE_JOB_KINDS:
                    db.get(DocumentRevision, job.revision_id).status = "PARSE_FAILED"
            if job.status == "RETRY_WAIT" and job.next_attempt_at <= now:
                job.status = "QUEUED"
            if job.status != "QUEUED" or job.next_attempt_at > now:
                continue
            stale_before = now - timedelta(seconds=settings.dispatch_stale_seconds)
            if job.last_dispatched_at is not None and job.last_dispatched_at > stale_before:
                continue
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.job_id == job.id).with_for_update())
            if event is None:
                db.add(OutboxEvent(job_id=job.id))
                recovered += 1
            elif event.status == "SENT" or (event.status == "INFLIGHT" and event.lease_until <= now):
                event.status, event.claim_token, event.lease_until = "PENDING", None, None
                recovered += 1
    return recovered


def dispatch_once(factory, sender, settings: Settings) -> bool:
    with factory.begin() as db:
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.status == "PENDING")
                          .order_by(OutboxEvent.created_at).limit(1).with_for_update(skip_locked=True))
        if event is None:
            return False
        event.status, event.claim_token = "INFLIGHT", uid()
        event.lease_until = utcnow() + timedelta(seconds=30)
        event_id, job_id, token = event.id, event.job_id, event.claim_token
    try:
        sender(job_id)  # Network call outside the DB transaction.
    except Exception:
        with factory.begin() as db:
            event = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update())
            if event.claim_token == token:
                event.status, event.claim_token, event.lease_until = "PENDING", None, None
        raise
    with factory.begin() as db:
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update())
        if event.claim_token == token:
            event.status, event.lease_until = "SENT", None
            db.get(Job, job_id).last_dispatched_at = utcnow()
    return True
