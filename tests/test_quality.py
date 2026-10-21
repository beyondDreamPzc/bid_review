"""质量规则、原文不可变、人工核对权限与新版本隔离。"""
import uuid

import pytest
from sqlalchemy import func, select

from app import quality
from app.jobs import run_job
from app.models import PageQualityReview, ParseArtifact
from app.storage import BlobStore
from tests.conftest import minimal_pdf
from tests.test_business import Scenario


def block(text, box=None, number=1):
    return {"block_id": f"p0001-b{number:04d}", "page":1, "text":text, "bbox":box or [50,50,300,65]}


@pytest.mark.parametrize("blocks, expected", [
    ([], {"NO_TEXT"}),
    ([block("Cover")], {"SPARSE_TEXT"}),
    ([block("正文内容足够长，用于构造没有明显规则异常的页面，并不表示没有提取遗漏。")], set()),
    ([block("bad\ufffd glyph (cid:123) and sufficiently long text content")], {"SUSPECT_ENCODING"}),
    ([block("long enough text for a coordinate check, outside page", [-10,50,300,65])], {"INVALID_BBOX"}),
    ([block("long enough text for a repeated layer detection example", number=1),
      block("long enough text for a repeated layer detection example", number=2)], {"OVERLAPPING_BLOCKS"}),
])
def test_explainable_page_rules(blocks, expected):
    result = quality.page_diagnostics({"page":1,"width":612,"height":792}, blocks)
    assert {f["code"] for f in result["findings"]} == expected
    assert result["block_count"] == len(blocks)
    assert all(f["message"] and f["suggestion"] for f in result["findings"])


def body(decision="TEXT_USABLE", version=0):
    return {"expected_version":version,"expected_diagnostic_profile":quality.PROFILE,
        "decision":decision,"note":"构造样本：已回看原件核对本页文字。"}


def write(s, artifact, values, who="owner", status=201, key=None, page=1):
    response=s.client.post(f"/api/v1/artifacts/{artifact}/pages/{page}/quality-reviews", json=values,
        headers={**s.auth(who),"Idempotency-Key":key or str(uuid.uuid4())})
    assert response.status_code==status, response.text
    return response


def test_quality_review_history_idempotency_and_revision_isolation(environment):
    s=Scenario(environment)
    s.ready()
    aid=s.response["artifact_id"]
    url=f"/api/v1/artifacts/{aid}"
    before=s.client.get(url+"/blocks").json()
    epoch=s.get("/workspace")["review_epoch"]
    with s.factory() as db:
        original_hash=db.get(ParseArtifact,aid).sha256
    initial=s.client.get(url+"/quality").json()
    assert initial["reviewed_page_count"]==0 and initial["parser_profile"]=="pdfplumber-probe-v1"
    key=str(uuid.uuid4())
    first=write(s,aid,body(),who="editor",key=key).json()
    assert write(s,aid,body(),who="editor",key=key).json()==first
    assert first["reviewer_name"]=="editor" and first["version"]==1
    write(s,aid,body(),who="reviewer",status=409)
    second=write(s,aid,body("NEEDS_REPROCESS",1),who="reviewer").json()
    assert second["version"]==2
    report=s.client.get(url+"/quality").json()
    assert report["reviewed_page_count"]==1 and report["needs_reprocess_page_count"]==1 and report["usable_page_count"]==0
    history=s.client.get(url+"/pages/1/quality-reviews").json()
    assert [r["version"] for r in history]==[2,1]
    assert s.client.get(url+"/pages/1/quality-reviews?offset=1&limit=1").json()==[first]
    assert s.client.get(url+"/blocks").json()==before
    with s.factory() as db:
        assert db.get(ParseArtifact,aid).sha256==original_hash
        assert db.scalar(select(func.count()).select_from(PageQualityReview))==2
    assert s.get("/workspace")["review_epoch"]==epoch
    revised=s.upload("RESPONSE","Respond within 2 hours",document_id=s.response["document_id"])
    new=s.client.get(f"/api/v1/artifacts/{revised['artifact_id']}/quality").json()
    assert new["reviewed_page_count"]==0 and new["pages"][0]["latest_review"] is None
    assert s.client.get(url+"/quality").json()["pages"][0]["latest_review"]["version"]==2


def test_empty_page_decisions_permissions_and_conflicts(environment):
    s=Scenario(environment)
    upload=s.client.post(s.root+"/documents", data={"title":"Blank test PDF","kind":"EVIDENCE"},
        files={"file":("blank.pdf",minimal_pdf(""),"application/pdf")},
        headers={**s.auth(),"Idempotency-Key":str(uuid.uuid4())}).json()
    result=run_job(s.factory,upload["job_id"],s.settings)
    assert result["status"]=="SUCCEEDED"
    aid=result["artifact_id"]
    report=s.client.get(f"/api/v1/artifacts/{aid}/quality").json()
    assert report["warning_page_count"]==1 and report["pages"][0]["findings"][0]["code"]=="NO_TEXT"
    write(s,aid,body(),status=409)
    write(s,aid,body("NEEDS_REPROCESS"),who="reader",status=403)
    write(s,aid,{**body(),"expected_diagnostic_profile":"another-profile"},status=409)
    write(s,aid,body("BLANK_CONFIRMED"))
    report=s.client.get(f"/api/v1/artifacts/{aid}/quality").json()
    assert report["warning_page_count"]==1 and report["usable_page_count"]==1
    write(s,s.tender["artifact_id"],body("BLANK_CONFIRMED"),status=409)
    write(s,aid,body(),page=2,status=404)
    assert s.client.get(f"/api/v1/artifacts/{aid}/pages/2/quality-reviews").status_code==404
    for suffix in ("/quality","/pages/1/quality-reviews"):
        assert s.client.get(f"/api/v1/artifacts/{aid}"+suffix,
            headers={"X-API-Key":"outsider-test-api-key-long"}).status_code==404


def test_corrupted_artifact_never_looks_like_a_clean_report(environment):
    s=Scenario(environment)
    aid=s.tender["artifact_id"]
    with s.factory() as db:
        artifact=db.get(ParseArtifact,aid)
        BlobStore(s.settings.storage_path).path(artifact.storage_key).write_bytes(b'{}')
    response=s.client.get(f"/api/v1/artifacts/{aid}/quality")
    assert response.status_code==503 and "完整性" in response.json()["detail"]
    write(s,aid,body(),status=503)
    with s.factory() as db:
        assert db.scalar(select(func.count()).select_from(PageQualityReview))==0
