import uuid

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models import DemoWorkspace, DocumentRevision, Project, ReviewIssue, WorkItem


@pytest.fixture
def demo(environment, monkeypatch):
    client, factory, settings = environment
    monkeypatch.setenv("BID_DEMO_ENABLED", "true")
    get_settings.cache_clear()
    response = client.post("/demo/api/session", json={})
    assert response.status_code == 200, response.text
    yield client, factory, response.json()


def state(client):
    response = client.get("/demo/api/session")
    assert response.status_code == 200, response.text
    return response.json()


def act(client, action, who="reviewer", expected=200, data=None, key=None, snapshot=None):
    snapshot = snapshot or state(client)
    task = snapshot["issue"]["task"] if snapshot["issue"] else {}
    body = {"expected_epoch": snapshot["versions"]["epoch"],
        "expected_material_set_id": snapshot["versions"]["material_set_id"],
        "expected_task_version": task.get("version"),
        "submission_id": (task.get("current_submission") or {}).get("id"), **(data or {})}
    response = client.post("/demo/api/actions/" + action, json=body,
        headers={"X-Demo-Actor": who, "Idempotency-Key": key or str(uuid.uuid4())})
    assert response.status_code == expected, response.text
    return response


def test_demo_is_off_by_default_and_has_no_bootstrap_key_exposure(environment):
    client, _, _ = environment
    assert client.get("/").status_code == 200
    assert client.post("/demo/api/session", json={}).status_code == 404
    assert client.get("/assets/app.js").status_code == 200


def test_demo_chinese_pdf_sources_and_cookie_scoped_access(demo):
    client, factory, data = demo
    assert data["hours"] == 4 and data["report"]["reviewed_count"] == 0
    assert "2小时" in data["requirements"][0]["tender"]["quote"]
    assert "4小时" in data["requirements"][0]["response"]["quote"]
    source = data["requirements"][0]["response"]
    assert source["page"] == 2
    assert client.get(source["original_url"]).content.startswith(b"%PDF-")
    assert client.get("/demo/api/documents/" + source["revision_id"]).json()["page_count"] == 3
    assert "api_key" not in str(data).lower()
    assert client.post("/demo/api/session", json={}, headers={"Origin": "https://unrelated.example"}).status_code == 403
    cookie = client.cookies.get("bid_demo_session")
    fresh = client.post("/demo/api/session", json={"reset": True}).json()
    assert client.cookies.get("bid_demo_session") != cookie
    assert fresh["requirements"][0]["id"] != data["requirements"][0]["id"]
    assert client.get(source["original_url"]).status_code == 404
    client.cookies.clear()
    assert client.get("/demo/api/session").status_code == 401
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(DemoWorkspace)) == 2


def test_demo_complete_flow_persists_history_and_invalidates_on_new_file(demo):
    client, factory, initial = demo
    open_key = str(uuid.uuid4())
    act(client, "open-issue", key=open_key, snapshot=initial)
    act(client, "open-issue", key=open_key, snapshot=initial)
    act(client, "start", who="reviewer", expected=403)
    act(client, "start", who="editor")
    before_submit = state(client)
    submit_key = str(uuid.uuid4())
    act(client, "submit", who="editor", data={"hours": 2}, key=submit_key, snapshot=before_submit)
    act(client, "submit", who="editor", data={"hours": 2}, key=submit_key, snapshot=before_submit)
    submitted = state(client)
    assert submitted["hours"] == 2 and len(submitted["files"]) == 2
    assert submitted["issue"]["task"]["status"] == "SUBMITTED"
    act(client, "review", who="editor", expected=403)
    review_key = str(uuid.uuid4())
    act(client, "review", key=review_key, snapshot=submitted)
    act(client, "review", key=review_key, snapshot=submitted)
    reviewed = state(client)
    assert reviewed["report"]["reviewed_count"] == 1
    act(client, "confirm", data={"requirement_ids": [r["id"] for r in reviewed["requirements"]][1:]})
    completed = state(client)
    assert completed["report"]["manual_review_complete"]
    report = client.get("/demo/api/report")
    assert "本轮已完成" in report.text and report.headers["Content-Disposition"].startswith("attachment;")
    assert "采购方要求" in report.text
    update_key = str(uuid.uuid4())
    act(client, "new-version", who="editor", key=update_key, snapshot=completed)
    act(client, "new-version", who="editor", key=update_key, snapshot=completed)
    changed = state(client)
    assert changed["issue"]["task"]["effective_status"] == "NEEDS_RECHECK"
    assert changed["report"]["reviewed_count"] == 0 and len(changed["files"]) == 3
    act(client, "start", who="editor")
    act(client, "submit", who="editor", data={"hours": 2})
    rechecked = state(client)
    assert rechecked["requirements"][0]["response"]["revision_no"] == 3  # Do not revert to the old second edition.
    assert len(rechecked["files"]) == 3
    act(client, "review")
    assert state(client)["report"]["reviewed_count"] == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ReviewIssue)) == 1
        assert db.scalar(select(func.count()).select_from(WorkItem)) == 1


def test_demo_stale_actions_do_not_publish_files_and_return_flow_works(demo):
    client, factory, _ = demo
    act(client, "open-issue")
    act(client, "start", who="editor")
    act(client, "submit", who="editor", data={"expected_task_version": 1}, expected=409)
    assert len(state(client)["files"]) == 1
    act(client, "submit", who="editor", data={"hours": 4})
    act(client, "review", data={"decision": "RETURN", "note": "还是4小时，请修正。"})
    assert state(client)["issue"]["task"]["status"] == "RETURNED"
    act(client, "start", who="editor")
    act(client, "submit", who="editor", data={"hours": 2})
    act(client, "review")
    assert [d["decision"] for d in state(client)["issue"]["task"]["decisions"]] == ["RETURN", "ACCEPT"]
