"""在 Compose 内验证真实 HTTP/MySQL/Redis/Worker 的人工业务闭环。

文件与账号均为人工构造的测试数据；每次运行新建项目，不打印或持久化明文密钥。
"""
import argparse
import io
import json
import os
import secrets
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from dotenv import load_dotenv
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import ReviewIssue, User, WorkItem
from app.storage import sha256


def synthetic_pdf(text):
    """生成 ASCII 测试 PDF；正文明确为构造样本，不冒充企业实际投标文件。"""
    content = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("ascii")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    output, offsets = io.BytesIO(), [0]
    output.write(b"%PDF-1.4\n")
    for number, obj in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = output.tell()
    output.write(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return output.getvalue()


def main():
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--browser-session", action="store_true", help="用不同账号的 Cookie 会话运行完整闭环，验证网页使用的真实身份认证")
    args = parser.parse_args()
    keys = {"owner": os.environ["BID_BOOTSTRAP_API_KEY"],
            "editor": secrets.token_urlsafe(36), "reviewer": secrets.token_urlsafe(36)}
    with SessionLocal.begin() as db:
        assert db.bind.dialect.name == "mysql", "Run this integration check against MySQL"
        for who in ("editor", "reviewer"):
            db.add(User(name=f"synthetic-{who}", api_key_hash=sha256(keys[who].encode())))

    with ExitStack() as stack:
        clients = {who: stack.enter_context(httpx.Client(base_url=args.base_url, timeout=30, trust_env=False)) for who in keys}
        parsed = urlsplit(args.base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if args.browser_session:
            for who, client in clients.items():
                login = client.post("/api/v1/auth/session", json={"api_key": keys[who]}, headers={"Origin": origin})
                assert login.status_code == 200, "Browser login failed"
                assert keys[who] not in login.text
        def call(method, path, *, who="owner", status=200, key=None, **kwargs):
            headers = {"Origin": origin} if args.browser_session else {"X-API-Key": keys[who]}
            if method == "POST":
                headers["Idempotency-Key"] = key or str(uuid.uuid4())
            response = clients[who].request(method, path, headers=headers, **kwargs)
            assert response.status_code == status, f"{method} {path}: {response.status_code} {response.text}"
            return response.json()

        ids = {who: call("GET", "/api/v1/me", who=who)["id"] for who in keys}
        project = call("POST", "/api/v1/projects", json={"name": "Synthetic 2-hour vs 4-hour workflow"}, status=201)["id"]
        prefix = f"/api/v1/projects/{project}"
        def get(path):
            return call("GET", prefix + path)
        def post(path, body, who="owner", status=200, key=None):
            return call("POST", prefix + path, json=body, who=who, status=status, key=key)
        def epoch():
            return get("/workspace")["review_epoch"]
        for who in ("editor", "reviewer"):
            post("/members", {"user_id": ids[who], "role": who.upper()})

        def upload(kind, text, document_id=None):
            route = f"/api/v1/documents/{document_id}/revisions" if document_id else prefix + "/documents"
            file = synthetic_pdf(text)
            uploaded = call("POST", route, data={} if document_id else {"kind": kind, "title": "Synthetic " + kind},
                files={"file": ("synthetic.pdf", file, "application/pdf")}, status=202)
            for _ in range(90):
                job = call("GET", "/api/v1/jobs/" + uploaded["job_id"])
                if job["status"] == "SUCCEEDED":
                    break
                assert job["status"] != "FAILED", job
                time.sleep(1)
            else:
                raise TimeoutError("The real worker did not complete the parse job")
            artifact = job["artifact_id"]
            block = call("GET", f"/api/v1/artifacts/{artifact}/blocks")[0]
            return {"upload": uploaded, "ref": {"artifact_id": artifact, "block_id": block["block_id"]}}

        tender = upload("TENDER", "Synthetic tender: response within 2 hours")
        response = upload("RESPONSE", "Synthetic response: response within 4 hours")
        req = post("/requirements", {"title": "响应时限", "text": "故障响应不得超过2小时。", "category": "TECHNICAL",
            "priority": "MANDATORY", "sources": [tender["ref"]]}, "editor", 201)
        post(f"/requirements/{req['requirement_id']}/confirm", {"expected_revision_no": 1}, "reviewer")
        baseline = post("/baselines", {"expected_epoch": epoch(), "requirement_revision_ids": [req["revision_id"]]}, "reviewer", 201)

        def materials(file):
            workspace = get("/workspace")
            return post("/material-sets", {"expected_epoch": workspace["review_epoch"],
                "expected_current_material_set_id": workspace["current_material_set_id"],
                "items": [{"artifact_id": file["ref"]["artifact_id"], "submission_role": "FORMAL_RESPONSE"}]}, "editor", 201)
        materials(response)
        assert get("/review-report")["reviewed_count"] == 0
        body = {"expected_epoch": epoch(), "requirement_revision_id": req["revision_id"],
            "title": "4小时响应与2小时要求冲突", "description": "已核对构造样本：招标为2小时，正式响应为4小时。",
            "kind": "CONFLICT", "severity": "HIGH", "assignee_id": ids["editor"], "evidence": [response["ref"]]}
        issue_key = str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=4) as executor:
            issues = list(executor.map(lambda _: post("/issues", body, "reviewer", 201, issue_key), range(4)))
        assert all(row == issues[0] for row in issues)
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(ReviewIssue).where(ReviewIssue.project_id == project)) == 1
            assert db.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.project_id == project)) == 1
        task = issues[0]["task"]
        task_path = f"/tasks/{task['id']}"
        task = post(task_path + "/transitions", {"action": "START", "expected_version": task["version"], "expected_epoch": epoch()}, "editor")
        corrected = upload("RESPONSE", "Synthetic corrected response: response within 2 hours", response["upload"]["document_id"])
        materials(corrected)
        task = post(task_path + "/transitions", {"action": "SUBMIT", "expected_version": task["version"], "expected_epoch": epoch(),
            "note": "已修改正式响应为2小时，提交人工复核。", "evidence": [corrected["ref"]]}, "editor")
        decision = {"expected_version": task["version"], "submission_id": task["current_submission"]["id"],
            "decision": "ACCEPT", "note": "已核对修订版原文，接受整改。"}
        post(task_path + "/decisions", decision, "editor", 403)
        task = post(task_path + "/decisions", decision, "reviewer")
        assert not get("/review-report")["manual_review_complete"]
        post("/requirement-decisions", {"expected_epoch": epoch(), "requirement_revision_id": req["revision_id"],
            "decision": "CONFIRMED_SATISFIED", "note": "人工逐项核对后确认此要求满足。", "evidence": [corrected["ref"]]}, "reviewer", 201)
        completed = get("/review-report")
        assert completed["manual_review_complete"] and completed["status"] == "REVIEW_COMPLETE"
        snapshot = get("/workbench")
        assert snapshot["report"] == completed
        assert len(next(d for d in snapshot["documents"] if d["id"] == response["upload"]["document_id"])["revisions"]) == 2
        report_file = clients["owner"].get(prefix + "/review-report/export",
            headers={} if args.browser_session else {"X-API-Key": keys["owner"]})
        assert report_file.status_code == 200 and "原件 SHA-256" in report_file.text
        materials(corrected)
        changed = get("/review-report")
        assert not changed["manual_review_complete"] and changed["reviewed_count"] == 0
        assert get("/tasks")[0]["effective_status"] == "NEEDS_RECHECK"
        result = {"database": "mysql", "queue": "redis/celery", "sample_type": "SYNTHETIC", "review_mode": "HUMAN",
            "authentication": "BROWSER_SESSION" if args.browser_session else "API_KEY",
            "project_id": project, "baseline_id": baseline["id"], "parallel_idempotent_issue_requests": 4,
            "unique_issue_count": 1, "unique_task_count": 1, "response_revision_no": corrected["upload"]["revision_no"],
            "independent_review_verified": True, "task_status_before_input_change": task["status"],
            "completed_report": completed, "after_material_change": changed,
            "history_preserved": len(get(task_path + "/submissions")) == 1 and len(get("/requirement-decisions")) == 1}
        (root / "docs" / "business-smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({name: result[name] for name in ("database", "queue", "sample_type", "parallel_idempotent_issue_requests",
            "unique_issue_count", "unique_task_count", "response_revision_no", "independent_review_verified", "history_preserved")}, ensure_ascii=False))
        print("Completed report: REVIEW_COMPLETE; after publishing another snapshot: NEEDS_RECHECK")
        if args.browser_session:
            for client in clients.values():
                assert client.delete("/api/v1/auth/session", headers={"Origin":origin}).status_code == 200
                assert client.get("/api/v1/projects").status_code == 401
            print("Browser-session login, authenticated report download and revocation verified")


if __name__ == "__main__":
    main()
