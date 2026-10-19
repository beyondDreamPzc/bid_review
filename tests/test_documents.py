from datetime import timedelta

from sqlalchemy import func, select

from app.database import utcnow
from app.jobs import (StaleLease, claim_job, dispatch_once, persist_result,
                      recover_jobs, run_job)
from app.models import DocumentRevision, Job, OutboxEvent, ParseArtifact, User
from app.parsers import probe_pdf
from app.services import ingest_pdf
from app.storage import BlobStore
from tests.conftest import minimal_pdf, upload


def project(client):
    result = client.post("/api/v1/projects", json={"name": "IT procurement"})
    assert result.status_code == 201
    return result.json()["id"]


def test_authentication_and_project_scope(environment):
    client, factory, settings = environment
    project_id = project(client)
    result = upload(client, project_id).json()
    client.headers["X-API-Key"] = "outsider-test-api-key-long"
    assert client.get(f"/api/v1/jobs/{result['job_id']}").status_code == 404
    assert upload(client, project_id).status_code == 404
    client.headers.pop("X-API-Key")
    assert client.get("/api/v1/projects").status_code == 401


def test_upload_is_idempotent_and_conflicting_key_rejected(environment):
    client, factory, settings = environment
    project_id = project(client)
    first = upload(client, project_id)
    assert first.status_code == 202
    assert upload(client, project_id).json() == first.json()
    conflict = upload(client, project_id, minimal_pdf("Changed"))
    assert conflict.status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1


def test_idempotent_replay_releases_transaction_before_return(environment):
    client, factory, settings = environment
    project_id = project(client)
    with factory() as db:
        user = db.scalar(select(User).where(User.name == "owner"))
        args = (db, BlobStore(settings.storage_path), user, project_id,
                minimal_pdf(), "Tender", "TENDER", "transaction-release-key", settings.parser_profile)
        first = ingest_pdf(*args)
        assert not db.in_transaction()
        assert ingest_pdf(*args) == first
        assert not db.in_transaction()


def test_revisions_preserve_originals_and_deduplicate_content(environment):
    client, factory, settings = environment
    project_id = project(client)
    first = upload(client, project_id).json()
    route = f"/api/v1/documents/{first['document_id']}/revisions"
    second = client.post(route, files={"file": ("v2.pdf", minimal_pdf("2 hours"))},
                         headers={"Idempotency-Key": "revision-request-0002"}).json()
    assert second["revision_no"] == 2
    assert second["sha256"] != first["sha256"]
    duplicate = client.post(route, files={"file": ("same.pdf", minimal_pdf("2 hours"))},
                            headers={"Idempotency-Key": "revision-request-0003"}).json()
    assert duplicate["revision_id"] == second["revision_id"]
    assert duplicate["reused"]
    assert client.get(f"/api/v1/revisions/{first['revision_id']}/original").content == minimal_pdf()
    assert len(client.get(route).json()) == 2


def test_probe_persists_traceable_sources_and_never_claims_review_ready(environment):
    client, factory, settings = environment
    item = upload(client, project(client)).json()
    run = run_job(factory, item["job_id"], settings)
    assert run["status"] == "SUCCEEDED"
    assert run_job(factory, item["job_id"], settings)["status"] == "IGNORED"
    artifact_id = run["artifact_id"]
    artifact = client.get(f"/api/v1/artifacts/{artifact_id}").json()
    assert artifact["quality_status"] == "NEEDS_REVIEW"
    assert artifact["formal_review_ready"] is False
    blocks = client.get(f"/api/v1/artifacts/{artifact_id}/blocks").json()
    assert "4 hours" in blocks[0]["text"]
    source = client.get(f"/api/v1/artifacts/{artifact_id}/blocks/{blocks[0]['block_id']}/source").json()
    assert source["page"] == 1 and len(source["bbox"]) == 4
    assert source["revision_sha256"] == item["sha256"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ParseArtifact)) == 1


def test_stale_worker_cannot_commit_after_recovery(environment):
    import pytest
    client, factory, settings = environment
    item = upload(client, project(client)).json()
    old = claim_job(factory, item["job_id"], settings)
    assert claim_job(factory, item["job_id"], settings) is None
    with factory.begin() as db:
        db.get(Job, item["job_id"]).lease_until = utcnow() - timedelta(seconds=1)
    recover_jobs(factory, settings)
    current = claim_job(factory, item["job_id"], settings)
    assert current.token > old.token
    result = probe_pdf(minimal_pdf(), 300, lambda: None)
    with pytest.raises(StaleLease):
        persist_result(factory, old, result, BlobStore(settings.storage_path))
    persist_result(factory, current, result, BlobStore(settings.storage_path))
    with factory() as db:
        assert db.get(Job, item["job_id"]).status == "SUCCEEDED"
        assert db.scalar(select(func.count()).select_from(ParseArtifact)) == 1


def test_lost_dispatch_is_recreated_from_database(environment):
    client, factory, settings = environment
    item = upload(client, project(client)).json()
    sent = []
    assert dispatch_once(factory, sent.append, settings)
    assert sent == [item["job_id"]]
    with factory.begin() as db:
        db.get(Job, item["job_id"]).last_dispatched_at = utcnow() - timedelta(minutes=10)
    assert recover_jobs(factory, settings) == 1
    assert dispatch_once(factory, sent.append, settings)
    assert len(sent) == 2


def test_corrupted_pdf_is_visible_failure_not_empty_success(environment):
    client, factory, settings = environment
    item = upload(client, project(client), b"%PDF-1.4\ncorrupted").json()
    run_job(factory, item["job_id"], settings)
    status = client.get(f"/api/v1/jobs/{item['job_id']}").json()
    assert status["status"] == "FAILED"
    assert status["error_code"] == "PDF_REJECTED"
    assert status["artifact_id"] is None


def test_file_type_and_limit_are_enforced(environment):
    client, factory, settings = environment
    project_id = project(client)
    assert upload(client, project_id, b"not a pdf").status_code == 415
    original = settings.max_upload_bytes
    settings.max_upload_bytes = 8
    try:
        assert upload(client, project_id).status_code == 413
    finally:
        settings.max_upload_bytes = original
