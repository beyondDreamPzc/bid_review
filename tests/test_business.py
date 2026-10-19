"""人工审查闭环的跨接口验收：真实 HTTP 权限、不可变来源、版本失效和复核。"""
import uuid

import pytest
from sqlalchemy import func, select

from app.jobs import run_job
from app.models import ReviewIssue, User, WorkItem
from app.storage import sha256
from tests.conftest import minimal_pdf


class Scenario:
    def __init__(self, environment):
        self.client, self.factory, self.settings = environment
        self.keys = {"owner": "owner-test-api-key-long-enough"}
        with self.factory.begin() as db:
            for name in ("editor", "reviewer", "reader"):
                self.keys[name] = f"{name}-business-test-key-long-enough"
                db.add(User(name=name, api_key_hash=sha256(self.keys[name].encode())))
        self.project = self.client.post("/api/v1/projects", json={"name": "Synthetic tender review"}).json()["id"]
        self.root = f"/api/v1/projects/{self.project}"
        self.ids = {name: self.client.get("/api/v1/me", headers=self.auth(name)).json()["id"] for name in self.keys}
        for name in ("editor", "reviewer", "reader"):
            self.post("/members", {"user_id": self.ids[name], "role": name.upper()})
        self.tender = self.upload("TENDER", "Respond within 2 hours")
        self.response = self.upload("RESPONSE", "Respond within 4 hours")
        self.req = self.post("/requirements", self.requirement_body(), who="editor", status=201).json()

    def auth(self, who="owner"):
        return {"X-API-Key": self.keys[who]}

    def post(self, path, body, who="owner", status=200, key=None):
        response = self.client.post(self.root + path, json=body, headers={
            **self.auth(who), "Idempotency-Key": key or str(uuid.uuid4())})
        assert response.status_code == status, response.text
        return response

    def get(self, path, who="owner"):
        response = self.client.get(self.root + path, headers=self.auth(who))
        assert response.status_code == 200, response.text
        return response.json()

    def upload(self, kind, text, document_id=None):
        route = f"/api/v1/documents/{document_id}/revisions" if document_id else self.root + "/documents"
        response = self.client.post(route, data={} if document_id else {"title": kind, "kind": kind},
            files={"file": ("synthetic.pdf", minimal_pdf(text), "application/pdf")},
            headers={**self.auth(), "Idempotency-Key": str(uuid.uuid4())})
        assert response.status_code == 202, response.text
        item = response.json()
        result = run_job(self.factory, item["job_id"], self.settings)
        assert result["status"] == "SUCCEEDED", result
        blocks = self.client.get(f"/api/v1/artifacts/{result['artifact_id']}/blocks").json()
        return {**item, "artifact_id": result["artifact_id"], "block_id": blocks[0]["block_id"]}

    def ref(self, file):
        return {"artifact_id": file["artifact_id"], "block_id": file["block_id"]}

    def requirement_body(self):
        return {"title": "故障响应时限", "text": "故障响应不得超过2小时。", "category": "TECHNICAL",
            "priority": "MANDATORY", "sources": [self.ref(self.tender)]}

    def baseline(self):
        self.req = self.post(f"/requirements/{self.req['requirement_id']}/confirm",
            {"expected_revision_no": self.req["revision_no"]}, who="reviewer").json()
        workspace = self.get("/workspace")
        return self.post("/baselines", {"expected_epoch": workspace["review_epoch"],
            "expected_current_baseline_id": workspace["current_baseline_id"],
            "requirement_revision_ids": [self.req["revision_id"]]}, who="reviewer", status=201).json()

    def materials(self, file=None, extra=None):
        workspace = self.get("/workspace")
        return self.post("/material-sets", {"expected_epoch": workspace["review_epoch"],
            "expected_current_material_set_id": workspace["current_material_set_id"],
            "items": [{"artifact_id": (file or self.response)["artifact_id"], "submission_role": "FORMAL_RESPONSE"}, *(extra or [])]}, status=201).json()

    def ready(self):
        self.baseline()
        self.materials()

    def issue_body(self, assignee="editor"):
        return {"expected_epoch": self.get("/workspace")["review_epoch"],
            "requirement_revision_id": self.req["revision_id"], "title": "响应承诺4小时，与2小时要求冲突",
            "description": "招标原文为2小时，正式响应为4小时，需修改并复核。", "kind": "CONFLICT",
            "severity": "HIGH", "assignee_id": self.ids[assignee], "evidence": [self.ref(self.response)]}

    def issue(self, assignee="editor"):
        return self.post("/issues", self.issue_body(assignee), who="reviewer", status=201).json()

    def transition(self, task, action, who="editor", file=None, status=200, version=None):
        return self.post(f"/tasks/{task['id']}/transitions", {"action": action,
            "expected_version": version or task["version"], "expected_epoch": self.get("/workspace")["review_epoch"],
            **({"note": "已修改为2小时响应，并核对正式文件。", "evidence": [self.ref(file or self.response)]} if action == "SUBMIT" else {})},
            who=who, status=status).json()

    def decision_body(self, task):
        return {"expected_version": task["version"], "submission_id": task["current_submission"]["id"],
            "decision": "ACCEPT", "note": "已回看原件，确认该版响应已修正。"}

    def accept(self, task, who="reviewer", status=200):
        return self.post(f"/tasks/{task['id']}/decisions", self.decision_body(task), who=who, status=status).json()

    def final(self, file=None, status=201):
        return self.post("/requirement-decisions", {"expected_epoch": self.get("/workspace")["review_epoch"],
            "requirement_revision_id": self.req["revision_id"], "decision": "CONFIRMED_SATISFIED",
            "note": "逐项核对正式响应书，人工确认满足此要求。", "evidence": [self.ref(file or self.response)]}, who="reviewer", status=status)


@pytest.fixture
def scenario(environment):
    return Scenario(environment)


def test_manual_business_flow_independent_review_and_idempotency(scenario):
    x = scenario
    x.ready()
    assert x.get("/review-report")["status"] == "IN_REVIEW"  # No issues != reviewed.
    payload, key = x.issue_body(), str(uuid.uuid4())
    issue = x.post("/issues", payload, who="reviewer", status=201, key=key).json()
    assert x.post("/issues", payload, who="reviewer", status=201, key=key).json() == issue
    assert issue["evidence"][0]["quote"] == "Respond within 4 hours"
    with x.factory() as db:
        assert db.scalar(select(func.count()).select_from(ReviewIssue)) == 1
        assert db.scalar(select(func.count()).select_from(WorkItem)) == 1
    x.final(status=409)
    task = x.transition(issue["task"], "START")
    fixed = x.upload("RESPONSE", "Respond within 2 hours", x.response["document_id"])
    x.materials(fixed)
    task = x.transition(task, "SUBMIT", file=fixed)
    task = x.accept(task)
    assert task["effective_status"] == "ACCEPTED"
    report = x.get("/review-report")
    assert report["manual_review_complete"] is False
    x.final(fixed)
    report = x.get("/review-report")
    assert report["manual_review_complete"] is True and report["reviewed_count"] == 1
    assert x.get("/issues")[0]["status"] == "RESOLVED"
    assert len(x.get(f"/tasks/{task['id']}/submissions")) == 1


def test_submitter_cannot_accept_or_return_their_own_submission(scenario):
    x = scenario
    x.ready()
    task = x.transition(x.issue("owner")["task"], "START", who="owner")
    task = x.transition(task, "SUBMIT", who="owner")
    x.accept(task, who="owner", status=403)
    body = {**x.decision_body(task), "decision": "RETURN"}
    x.post(f"/tasks/{task['id']}/decisions", body, who="owner", status=403)
    assert x.accept(task)["status"] == "ACCEPTED"


def test_material_change_invalidates_submission_and_final_conclusion(scenario):
    x = scenario
    x.ready()
    task = x.transition(x.issue()["task"], "START")
    task = x.transition(task, "SUBMIT")
    x.materials()  # Even the same bytes require an explicit review of this new snapshot.
    x.accept(task, status=409)
    assert x.get("/tasks")[0]["effective_status"] == "NEEDS_RECHECK"
    task = x.transition(task, "START")
    task = x.transition(task, "SUBMIT")
    task = x.accept(task)
    x.final()
    assert x.get("/review-report")["manual_review_complete"]
    x.materials()
    report = x.get("/review-report")
    assert report["status"] == "ISSUES_OPEN" and report["reviewed_count"] == 0
    assert report["requirements"][0]["current_decision"] is None
    assert len(x.get("/requirement-decisions")) == 1
    assert x.get("/issues")[0]["status"] == "NEEDS_RECHECK"
    assert len(x.get(f"/tasks/{task['id']}/submissions")) == 2


def test_return_and_optimistic_version_keep_immutable_submission_history(scenario):
    x = scenario
    x.ready()
    task = x.transition(x.issue()["task"], "START")
    x.transition(task, "SUBMIT", version=1, status=409)
    task = x.transition(task, "SUBMIT")
    first_submission = task["current_submission"]["id"]
    task = x.post(f"/tasks/{task['id']}/decisions", {**x.decision_body(task), "decision": "RETURN"}, who="reviewer").json()
    task = x.transition(task, "START")
    task = x.transition(task, "SUBMIT")
    x.post(f"/tasks/{task['id']}/decisions", {**x.decision_body(task), "submission_id": first_submission}, who="reviewer", status=409)
    task = x.accept(task)
    assert [row["decision"] for row in task["decisions"]] == ["RETURN", "ACCEPT"]
    assert len(x.get(f"/tasks/{task['id']}/submissions")) == 2


def test_requirement_draft_publication_and_old_baseline_remain_separate(scenario):
    x = scenario
    x.post("/baselines", {"expected_epoch": 0, "requirement_revision_ids": [x.req["revision_id"]]}, status=409)
    old = x.baseline()
    x.materials()
    x.final()
    assert x.get("/review-report")["manual_review_complete"]
    body = {**x.requirement_body(), "text": "澄清响应时限适用范围。", "expected_revision_no": 1}
    x.req = x.post(f"/requirements/{x.req['requirement_id']}/revisions", body, who="editor", status=201).json()
    report = x.get("/review-report")
    assert report["pending_requirement_changes"] and not report["manual_review_complete"]
    x.post(f"/requirements/{x.req['requirement_id']}/revisions", body, status=409)
    new = x.baseline()
    assert new["parent_id"] == old["id"]
    history = x.get("/baselines")
    assert history[0]["requirements"][0]["text"] == "故障响应不得超过2小时。"
    assert x.get("/review-report")["reviewed_count"] == 0


def test_formal_evidence_scope_and_roles(scenario):
    x = scenario
    x.baseline()
    reference = x.upload("EVIDENCE", "Reference response within 2 hours")
    x.materials(extra=[{"artifact_id": reference["artifact_id"], "submission_role": "REFERENCE"}])
    payload = x.issue_body()
    x.post("/issues", {**payload, "evidence": [x.ref(reference)]}, who="reviewer", status=422)
    x.post("/issues", {**payload, "assignee_id": x.ids["reader"]}, who="reviewer", status=422)
    x.post("/issues", payload, who="editor", status=403)
    x.post("/requirements", x.requirement_body(), who="reader", status=403)
    wrong_kind = {**x.requirement_body(), "sources": [x.ref(x.response)]}
    x.post("/requirements", wrong_kind, status=422)
    other_project = x.client.post("/api/v1/projects", json={"name": "Another project"}).json()["id"]
    result = x.client.post(f"/api/v1/projects/{other_project}/requirements", json=x.requirement_body(),
        headers={**x.auth(), "Idempotency-Key": str(uuid.uuid4())})
    assert result.status_code == 404
    assert x.client.get(x.root + "/issues", headers={"X-API-Key": "outsider-test-api-key-long"}).status_code == 404


def test_stale_epoch_and_incomplete_baseline_are_rejected(scenario):
    x = scenario
    x.ready()
    x.post("/issues", {**x.issue_body(), "expected_epoch": 0}, who="reviewer", status=409)
    workspace = x.get("/workspace")
    x.post("/baselines", {"expected_epoch": workspace["review_epoch"],
        "expected_current_baseline_id": workspace["current_baseline_id"],
        "requirement_revision_ids": [x.req["revision_id"], x.req["revision_id"]]}, status=409)
    materials = x.get("/material-sets")
    x.post("/material-sets", {"expected_epoch": 0, "expected_current_material_set_id": materials[-1]["id"],
        "items": [{"artifact_id": x.response["artifact_id"], "submission_role": "FORMAL_RESPONSE"}]}, status=409)


def test_new_issue_requires_new_final_decision_even_without_material_change(scenario):
    x = scenario
    x.ready()
    x.final()
    assert x.get("/review-report")["manual_review_complete"]
    task = x.transition(x.issue()["task"], "START")
    task = x.transition(task, "SUBMIT")
    x.accept(task)
    assert x.get("/review-report")["manual_review_complete"] is False
    x.final()
    decisions = x.get("/requirement-decisions")
    assert [d["review_version"] for d in decisions] == [0, 1]
    assert x.get("/review-report")["manual_review_complete"]
