"""真实 Cookie 账号、权限与文件换版跨接口验收。测试资料均为构造 PDF。"""
from datetime import timedelta
import uuid

from sqlalchemy import select

from app.models import User, WebSession, utcnow
from app.session_auth import COOKIE_NAME
from app.storage import sha256
from tests.test_business import Scenario

ORIGIN = {"Origin": "http://testserver"}


def login(client, key):
    client.headers.pop("X-API-Key", None)
    result = client.post("/api/v1/auth/session", json={"api_key": key}, headers=ORIGIN)
    assert result.status_code == 200, result.text
    assert key not in result.text
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    return result.json()


def post(client, path, body, status=200):
    response = client.post(path, json=body, headers={**ORIGIN, "Idempotency-Key": str(uuid.uuid4())})
    assert response.status_code == status, response.text
    return response.json()


def test_revocation_csrf_expiry_and_secret_redaction(environment):
    client, factory, _ = environment
    session = login(client, "owner-test-api-key-long-enough")
    token = client.cookies.get(COOKIE_NAME)
    with factory() as db:
        stored = db.scalar(select(WebSession))
        assert stored.token_hash == sha256(token.encode()) and stored.token_hash != token
    assert client.post("/api/v1/projects", json={"name":"Blocked"}).status_code == 403
    assert client.post("/api/v1/projects", json={"name":"Blocked"}, headers={"Origin":"https://other.example"}).status_code == 403
    project = post(client, "/api/v1/projects", {"name":"Cookie project"}, 201)
    assert client.get(f"/api/v1/projects/{project['id']}/workbench").json()["workspace"]["my_role"] == "OWNER"
    assert client.get("/api/v1/auth/session").json()["user"] == session["user"]
    # An explicit bad API key must not silently fall back to a valid ambient cookie.
    assert client.get("/api/v1/projects", headers={"X-API-Key":"bad-key"}).status_code == 401
    assert client.delete("/api/v1/auth/session", headers=ORIGIN).status_code == 200
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/v1/projects").status_code == 401
    login(client, "owner-test-api-key-long-enough")
    with factory.begin() as db:
        db.scalar(select(WebSession)).expires_at = utcnow() - timedelta(seconds=1)
    assert client.get("/api/v1/projects").status_code == 401
    secret = "never-echo-this-value-in-error"
    bad = client.post("/api/v1/auth/session", json={"api_key":{"secret":secret}}, headers=ORIGIN)
    assert bad.status_code == 422 and secret not in bad.text
    assert client.post("/api/v1/auth/session", json={"api_key":secret}, headers=ORIGIN).status_code == 401
    assert client.get("/workspace").status_code == 200


def test_workbench_isolation_versions_and_real_cookie_review(environment):
    s = Scenario(environment)
    s.ready()
    client = s.client
    login(client, s.keys["owner"])
    initial = client.get(s.root + "/workbench").json()
    assert len(initial["documents"]) == 2 and initial["baseline"]["requirements"][0]["title"] == "故障响应时限"
    assert initial["documents"][0]["revisions"][0]["job_status"] == "SUCCEEDED"
    issue = post(client, s.root+"/issues", s.issue_body(), 201)
    login(client, s.keys["editor"])
    task = post(client, s.root+f"/tasks/{issue['task']['id']}/transitions", {
        "action":"START", "expected_epoch":initial["workspace"]["review_epoch"], "expected_version":1})
    corrected = s.upload("RESPONSE", "Respond within 2 hours", document_id=s.response["document_id"])
    current = client.get(s.root+"/workbench").json()
    post(client, s.root+"/material-sets", {"expected_epoch":current["workspace"]["review_epoch"],
        "expected_current_material_set_id":current["workspace"]["current_material_set_id"],
        "items":[{"artifact_id":corrected["artifact_id"],"submission_role":"FORMAL_RESPONSE"}]}, 201)
    epoch = client.get(s.root+"/workspace").json()["review_epoch"]
    task = post(client, s.root+f"/tasks/{task['id']}/transitions", {"action":"SUBMIT",
        "expected_epoch":epoch,"expected_version":task["version"],"note":"已修改为2小时",
        "evidence":[s.ref(corrected)]})
    post(client, s.root+f"/tasks/{task['id']}/decisions", s.decision_body(task), 403)
    login(client, s.keys["reviewer"])
    post(client, s.root+f"/tasks/{task['id']}/decisions", s.decision_body(task))
    post(client, s.root+"/requirement-decisions", {"expected_epoch":epoch,"requirement_revision_id":s.req["revision_id"],
        "decision":"CONFIRMED_SATISFIED","note":"核对新版原件满足要求","evidence":[s.ref(corrected)]}, 201)
    final = client.get(s.root+"/workbench").json()
    assert final["report"]["manual_review_complete"] is True
    assert len(next(d for d in final["documents"] if d["id"]==s.response["document_id"])["revisions"]) == 2
    exported = client.get(s.root+"/review-report/export")
    assert exported.status_code == 200 and "原件 SHA-256" in exported.text and "reviewer" in exported.text
    assert "filename=" in exported.headers["content-disposition"]
    # Real cookie login has no demo identity switch and cannot see another user's project.
    login(client, "outsider-test-api-key-long")
    assert client.get(s.root+"/workbench").status_code == 404
    assert client.get(s.root+"/review-report/export").status_code == 404
    assert client.get(s.root+"/member-candidates?q=ow").status_code == 404


def test_candidates_restricted_and_latest_draft_not_frozen(environment):
    s = Scenario(environment)
    s.ready()
    with s.factory.begin() as db:
        db.add(User(name="新建同事", api_key_hash=sha256(b"candidate-long-enough-api-key")))
    login(s.client, s.keys["owner"])
    found = s.client.get(s.root+"/member-candidates?q=新建").json()
    assert len(found)==1 and found[0]["name"]=="新建同事" and "api_key_hash" not in found[0]
    assert s.client.get(s.root+"/member-candidates", params={"q":"  "}).status_code == 422
    post(s.client, s.root+f"/requirements/{s.req['requirement_id']}/revisions", {
        **s.requirement_body(), "text":"草稿要求变更为1小时", "expected_revision_no":1}, 201)
    snapshot = s.client.get(s.root+"/workbench").json()
    assert snapshot["requirements"][0]["revision_no"] == 2
    assert snapshot["baseline"]["requirements"][0]["revision_no"] == 1
    assert snapshot["report"]["pending_requirement_changes"] is True
    login(s.client, s.keys["editor"])
    assert s.client.get(s.root+"/member-candidates?q=新建").status_code == 403


def test_project_creation_idempotency(environment):
    client, _, _ = environment
    key = str(uuid.uuid4())
    first = client.post("/api/v1/projects", json={"name":"一次创建"}, headers={"Idempotency-Key":key})
    retry = client.post("/api/v1/projects", json={"name":"一次创建"}, headers={"Idempotency-Key":key})
    assert first.status_code == 201 and retry.json() == first.json()
    assert client.post("/api/v1/projects", json={"name":"其他名称"}, headers={"Idempotency-Key":key}).status_code == 409
    assert len(client.get("/api/v1/projects").json()) == 1
