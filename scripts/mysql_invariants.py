"""Concurrent API checks against the actual isolated MySQL deployment."""
import argparse
import json
import os
import secrets
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from dotenv import load_dotenv

from app.database import SessionLocal
from app.models import User
from app.storage import sha256
from tests.conftest import minimal_pdf


def main():
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    key = os.environ["BID_BOOTSTRAP_API_KEY"]
    with SessionLocal() as db:
        assert db.bind.dialect.name == "mysql", "This check must use MySQL"
    with httpx.Client(base_url=args.base_url, headers={"X-API-Key": key}, timeout=30, trust_env=False) as client:
        created = client.post("/api/v1/projects", json={"name": "MySQL concurrency verification"})
        created.raise_for_status()
        project_id = created.json()["id"]
        upload_key = str(uuid.uuid4())
        data = minimal_pdf()
        def upload(_):
            response = client.post(f"/api/v1/projects/{project_id}/documents",
                data={"title": "Concurrency fixture", "kind": "TENDER"},
                files={"file": ("fixture.pdf", data, "application/pdf")},
                headers={"Idempotency-Key": upload_key})
            response.raise_for_status()
            return response.json()
        with ThreadPoolExecutor(max_workers=6) as executor:
            responses = list(executor.map(upload, range(6)))
        assert all(response == responses[0] for response in responses)
        first = responses[0]
        def revision(index):
            response = client.post(f"/api/v1/documents/{first['document_id']}/revisions",
                files={"file": ("v.pdf", minimal_pdf(f"Revision {index}"), "application/pdf")},
                headers={"Idempotency-Key": str(uuid.uuid4())})
            response.raise_for_status()
            return response.json()
        with ThreadPoolExecutor(max_workers=4) as executor:
            versions = list(executor.map(revision, range(4)))
        assert sorted(version["revision_no"] for version in versions) == [2, 3, 4, 5]
        denied_key = secrets.token_urlsafe(36)
        with SessionLocal.begin() as db:
            db.add(User(name="scope-verification-user", api_key_hash=sha256(denied_key.encode())))
        for route in (f"/api/v1/jobs/{first['job_id']}",
                      f"/api/v1/documents/{first['document_id']}/revisions",
                      f"/api/v1/revisions/{first['revision_id']}/original"):
            assert client.get(route, headers={"X-API-Key": denied_key}).status_code == 404
        report = {"database": "mysql", "parallel_idempotent_uploads": 6,
                  "unique_document_ids": len({response["document_id"] for response in responses}),
                  "unique_job_ids": len({response["job_id"] for response in responses}),
                  "parallel_revision_numbers": sorted(version["revision_no"] for version in versions),
                  "cross_project_denials_verified": 3, "status": "passed"}
    output = root / "docs/mysql-invariants.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
