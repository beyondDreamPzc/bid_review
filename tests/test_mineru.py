"""归一化协议与业务不变量；真实SDK另由mineru_smoke运行验收。"""
import copy
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import func,select

from app import models as m
from app.jobs import StaleLease,run_job
from app.mineru_parser import DEFAULT_PROFILE,normalize,pdf_geometry,run_mineru
from app.parsers import ParseRejected
from tests.conftest import minimal_pdf
from tests.test_business import Scenario


def envelope():
    return {"runtime":{"mineru":"4.0.12","docvortex":"0.5.16"},"middle":{
        "schema":"docvortex.middle","schema_version":"2.0","is_full_document":True,
        "metadata":{"file_suffix":"pdf","producer":{"name":"mineru","version":"4.0.12"}},
        "extensions":{"mineru":{"tier":"flash","parse_mode":"txt"},"docvortex_layout":{
            "version":1,"pages":[{"page_idx":0,"width_pt":612,"height_pt":792}]}},
        "pages":[{"page_idx":0,"blocks":[{"type":"text","index":0,"bbox":[.1,.1,.8,.2],
            "content":[{"type":"text","content":"Respond within 2 hours"}]}]}]}}


def test_normalize_coordinates_nested_text_and_table_without_active_markup():
    raw=envelope()
    raw["middle"]["pages"][0]["blocks"].extend([
        {"type":"table","index":1,"bbox":[.1,.3,.8,.6],"content":[{"type":"table_body","content":
            '<table><tr><td>服务</td><td>2小时</td></tr></table><script>secret bad code</script>'}]},
        {"type":"list","index":2,"bbox":[.1,.6,.8,.8],"content":[{"type":"text","content":[
            {"type":"hyperlink","url":"https://example.org","content":[{"type":"text","content":"培训2次"}]}]}]}])
    before=copy.deepcopy(raw)
    result=normalize(raw,DEFAULT_PROFILE,[(612,792)])
    assert result["coordinate_system"]=="pdf_points_top_left" and result["blocks"][0]["bbox"]==[61.2,79.2,489.6,158.4]
    assert result["blocks"][1]["text"]=="服务\t2小时" and result["blocks"][2]["text"]=="培训2次"
    assert result["quality_status"]=="NEEDS_REVIEW" and not result["ready_for_review"]
    assert "TABLE_TEXT_FLATTENED" in result["quality_flags"] and raw==before


@pytest.mark.parametrize("failure",["schema","version","partial","missing_page","geometry","bbox","nan","order","tier"])
def test_incompatible_or_partial_results_cannot_create_sources(failure):
    raw=envelope();middle=raw["middle"]
    if failure=="schema":middle["schema"]="legacy.pdf_info"
    if failure=="version":raw["runtime"]["mineru"]="4.1.0"
    if failure=="partial":middle["is_full_document"]=False
    if failure=="missing_page":middle["pages"][0]["page_idx"]=1
    if failure=="geometry":middle["extensions"]["docvortex_layout"]["pages"][0]["width_pt"]=1000
    if failure=="bbox":middle["pages"][0]["blocks"][0]["bbox"]=[100,100,800,200]
    if failure=="nan":middle["pages"][0]["blocks"][0]["bbox"][0]=float("nan")
    if failure=="order":middle["pages"][0]["blocks"]*=2
    if failure=="tier":middle["extensions"]["mineru"]["tier"]="basic"
    with pytest.raises(ParseRejected):normalize(raw,DEFAULT_PROFILE,[(612,792)])


def test_blank_pages_retained_and_image_descriptions_not_used_as_verbatim_evidence():
    raw=envelope();raw["middle"]["pages"][0]["blocks"]=[{"type":"image","index":0,"bbox":[.1,.1,.8,.8],
        "content":[{"type":"image_body","content":"AI description, not original wording"}]}]
    result=normalize(raw,DEFAULT_PROFILE,[(612,792)])
    assert result["page_count"]==1 and result["block_count"]==0 and result["pages"][0]["flags"]


def test_preflight_rejects_corruption_and_page_limit_before_sdk():
    assert pdf_geometry(minimal_pdf(),300)==[(612,792)]
    with pytest.raises(ParseRejected):pdf_geometry(b"%PDF-corrupted",300)
    with pytest.raises(ParseRejected):pdf_geometry(minimal_pdf(),0)


@pytest.mark.parametrize("failure",["lease","timeout"])
def test_lost_lease_or_timeout_terminates_sdk_process(environment,monkeypatch,failure):
    _,_,settings=environment
    class Process:
        stopped=False
        def __init__(self,*args,**kwargs):pass
        def wait(self,timeout):
            if not self.stopped:raise subprocess.TimeoutExpired("fixture",timeout)
            return 0
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped=True
    process=Process();monkeypatch.setattr(subprocess,"Popen",lambda *a,**k:process)
    if failure=="timeout":
        times=iter([0,1000]);monkeypatch.setattr("app.mineru_parser.time",SimpleNamespace(monotonic=lambda:next(times)))
    calls=[]
    def beat():
        calls.append(1)
        if failure=="lease" and len(calls)>1:raise StaleLease("synthetic lost lease")
    from app.mineru_parser import MinerUUnavailable
    with pytest.raises(StaleLease if failure=="lease" else MinerUUnavailable):run_mineru(minimal_pdf(),DEFAULT_PROFILE,settings,beat)
    assert process.stopped


def test_missing_runtime_is_visible_retry_and_never_falls_back(environment):
    s=Scenario(environment);s.settings.parser_profile=DEFAULT_PROFILE;s.settings.mineru_python="/missing/mineru/python"
    body=s.client.post(f"/api/v1/revisions/{s.tender['revision_id']}/parse",json={},
        headers={**s.auth(),"Idempotency-Key":"missing-mineru-request"}).json()
    result=run_job(s.factory,body["job_id"],s.settings)
    assert result["error_type"]=="MinerUUnavailable"
    with s.factory() as db:
        job=db.get(m.Job,body["job_id"])
        assert job.status=="RETRY_WAIT" and job.artifact_id is None
        assert db.scalar(select(func.count()).select_from(m.ParseArtifact).where(m.ParseArtifact.revision_id==s.tender["revision_id"]))==1


def test_reparse_keeps_old_evidence_and_deduplicates_new_profile(environment,monkeypatch):
    s=Scenario(environment);before=s.get("/workspace");s.settings.parser_profile=DEFAULT_PROFILE
    route=f"/api/v1/revisions/{s.tender['revision_id']}/parse"
    key="reparse-synthetic-request"
    headers={**s.auth(),"Idempotency-Key":key}
    first=s.client.post(route,json={},headers=headers)
    assert first.status_code==202,first.text
    assert s.client.post(route,json={},headers=headers).json()==first.json()
    for role in ("reader","reviewer"):
        assert s.client.post(route,json={},headers={**s.auth(role),"Idempotency-Key":key}).status_code==403
    assert s.client.post(route,json={},headers={"X-API-Key":"outsider-test-api-key-long","Idempotency-Key":key}).status_code==404
    current=s.get("/workbench")
    revision=next(d for d in current["documents"] if d["id"]==s.tender["document_id"])["revisions"][0]
    assert revision["artifact_id"]==s.tender["artifact_id"] and revision["job_parser_profile"]==DEFAULT_PROFILE
    monkeypatch.setattr("app.mineru_parser.run_mineru",lambda *a,**k:normalize(envelope(),DEFAULT_PROFILE,[(612,792)]))
    result=run_job(s.factory,first.json()["job_id"],s.settings)
    assert result["status"]=="SUCCEEDED" and result["artifact_id"]!=s.tender["artifact_id"]
    assert s.get("/requirements")[0]["sources"][0]["artifact_id"]==s.tender["artifact_id"]
    assert s.get("/workspace")["review_epoch"]==before["review_epoch"]
    assert s.client.get(f"/api/v1/artifacts/{result['artifact_id']}/quality").json()["reviewed_page_count"]==0
    assert s.client.get(f"/api/v1/artifacts/{s.tender['artifact_id']}/blocks/{s.tender['block_id']}/source").status_code==200
    with s.factory() as db:
        assert db.scalar(select(func.count()).select_from(m.ParseArtifact).where(m.ParseArtifact.revision_id==s.tender["revision_id"]))==2


def test_reparse_failed_retry_cannot_overlap_another_active_profile(environment):
    s=Scenario(environment);s.settings.parser_profile=DEFAULT_PROFILE
    route=f"/api/v1/revisions/{s.tender['revision_id']}/parse"
    def submit(body,status):
        import uuid
        response=s.client.post(route,json=body,headers={**s.auth(),"Idempotency-Key":str(uuid.uuid4())})
        assert response.status_code==status,response.text
        return response.json()
    flash=submit({},202)
    s.settings.parser_profile="mineru-4.0.12-basic-auto-v1"
    submit({},409)
    with s.factory.begin() as db:db.get(m.Job,flash["job_id"]).status="FAILED"
    basic=submit({},202)
    s.settings.parser_profile=DEFAULT_PROFILE
    submit({"retry_failed":True},409)
    with s.factory.begin() as db:db.get(m.Job,basic["job_id"]).status="FAILED"
    retry=submit({"retry_failed":True},202)
    assert retry["job_id"]==flash["job_id"] and retry["reused"]
    with s.factory() as db:
        assert db.get(m.Job,flash["job_id"]).status=="QUEUED"
        assert db.get(m.OutboxEvent,db.scalar(select(m.OutboxEvent.id).where(m.OutboxEvent.job_id==flash["job_id"]))).status=="PENDING"


def test_punctuation_equivalent_lookup_does_not_rewrite_sources_or_merge_different_numbers(environment):
    from app.demo import block_for
    from scripts.evaluate_extraction import normalize as compare
    s=Scenario(environment)
    parsed=s.upload("EVIDENCE","Response: within 2 hours")
    with s.factory() as db:
        source=block_for(db,parsed["artifact_id"],"Response：")
        assert source.text=="Response: within 2 hours"  # Keep actual extraction, even when lookup accepts full-width punctuation.
    assert compare("响应时限：2小时")==compare("响应时限: 2小时")
    assert compare("响应时限：2小时")!=compare("响应时限:4小时")
