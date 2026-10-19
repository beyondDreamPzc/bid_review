"""Run the actual API -> MySQL/outbox -> Redis/worker -> source lookup path."""
import argparse
import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv


def main():
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, default=root / "data/samples/shanghai-12345-2023.pdf")
    parser.add_argument("--report", type=Path, default=root / "docs/sample-smoke.json")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    args = parser.parse_args()
    key = os.environ.get("BID_BOOTSTRAP_API_KEY")
    if not key:
        raise RuntimeError("BID_BOOTSTRAP_API_KEY is not set")
    payload = args.pdf.read_bytes()
    with httpx.Client(base_url=args.base_url, headers={"X-API-Key": key}, trust_env=False, timeout=60) as client:
        response = client.get("/health/ready")
        response.raise_for_status()
        project = client.post("/api/v1/projects", json={"name": "公开采购样本解析验证"})
        project.raise_for_status()
        project_id = project.json()["id"]
        request_key = str(uuid.uuid4())
        options = {"data": {"title": "上海12345市民感知平台二期（2023历史样本）", "kind": "TENDER"},
                   "files": {"file": ("public-tender.pdf", payload, "application/pdf")},
                   "headers": {"Idempotency-Key": request_key}}
        started = time.monotonic()
        upload = client.post(f"/api/v1/projects/{project_id}/documents", **options)
        upload.raise_for_status()
        item = upload.json()
        repeated = client.post(f"/api/v1/projects/{project_id}/documents", **options)
        repeated.raise_for_status()
        assert repeated.json() == item
        for _ in range(180):
            response = client.get(f"/api/v1/jobs/{item['job_id']}")
            response.raise_for_status()
            job = response.json()
            if job["status"] == "SUCCEEDED":
                break
            if job["status"] == "FAILED":
                raise RuntimeError(f"Job failed: {job['error_code']}: {job['error_detail']}")
            time.sleep(2)
        else:
            raise RuntimeError("Job did not finish within 360 seconds")
        response = client.get(f"/api/v1/artifacts/{job['artifact_id']}")
        response.raise_for_status()
        artifact = response.json()
        assert artifact["page_count"] == 65 and not artifact["formal_review_ready"]
        response = client.get(f"/api/v1/artifacts/{job['artifact_id']}/blocks", params={"page": 3, "limit": 200})
        response.raise_for_status()
        match = next(block for block in response.json() if "2023-10-16" in block["text"])
        response = client.get(f"/api/v1/artifacts/{job['artifact_id']}/blocks/{match['block_id']}/source")
        response.raise_for_status()
        source = response.json()
        assert source["page"] == 3 and source["revision_sha256"] == hashlib.sha256(payload).hexdigest()
        original = client.get(source["original_url"])
        original.raise_for_status()
        assert original.content == payload
        report = {"verified_at": datetime.now(UTC).isoformat(), "path": "API -> MySQL/outbox -> Redis/Celery -> persisted source",
                  "project_id": project_id, "job_id": item["job_id"], "artifact_id": job["artifact_id"],
                  "original_sha256": item["sha256"], "page_count": artifact["page_count"],
                  "block_count": artifact["block_count"], "elapsed_seconds": round(time.monotonic() - started, 2),
                  "parser_profile": artifact["parser_profile"], "quality_status": artifact["quality_status"],
                  "idempotent_upload_verified": True, "original_bytes_verified": True,
                  "source_page_verified": 3, "source_block_id": source["block_id"], "source_bbox": source["bbox"],
                  "formal_review_ready": False, "limitations": artifact["quality_flags"]}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
