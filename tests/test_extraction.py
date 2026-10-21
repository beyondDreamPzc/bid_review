"""合成模型 HTTP 契约与跨接口不变量；不调用真实云模型、不评价语义效果。"""
import copy
import json
import uuid
from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app import models as m
from app.extraction_jobs import run_extraction
from app.extraction_model import ExtractionError, config_snapshot, extract_batch
from app.jobs import recover_jobs
from tests.test_business import Scenario
from tests.conftest import minimal_pdf


def configured(environment):
    s=Scenario(environment)
    s.settings.llm_enabled=True
    s.settings.llm_base_url="https://fixture.invalid/v1"
    s.settings.llm_api_key=SecretStr("synthetic-test-key-not-a-real-credential")
    s.settings.llm_model="synthetic-contract-model"
    result=s.client.post(f"/api/v1/artifacts/{s.tender['artifact_id']}/pages/1/quality-reviews",
        json={"expected_version":0,"expected_diagnostic_profile":"text-quality-v1","decision":"TEXT_USABLE","note":"构造验收页"},
        headers={**s.auth(),"Idempotency-Key":str(uuid.uuid4())})
    assert result.status_code==201,result.text
    return s


def enqueue(s,who="owner"):
    config=s.client.get("/api/v1/extraction/config").json()
    return s.post("/extraction-runs",{"artifact_id":s.tender["artifact_id"],"pages":[1],
        "expected_config_fingerprint":config["config_fingerprint"],"acknowledge_external_processing":True},who=who,status=202).json()


def response_for(request,mode="ok"):
    body=json.loads(request.content)
    assert body["store"] is False and not body.get("tools")
    assert body["response_format"]["type"]=="json_schema"
    blocks=json.loads(body["messages"][1]["content"])["untrusted_document_blocks"]
    candidate={"title":"响应时限","text":"接报后2小时内响应。","category":"TECHNICAL","priority":"GENERAL",
        "rationale":"构造模型接口验收的建议，不代表真实模型判断。","block_ids":[blocks[0]["block_id"]]}
    if mode=="bad_source":candidate["block_ids"]=["not-provided"]
    if mode=="duplicate_source":candidate["block_ids"]*=2
    if mode=="bad_shape":candidate["unexpected"]="should be refused"
    message={"content":json.dumps({"candidates":[candidate]},ensure_ascii=False)}
    if mode=="refusal":message["refusal"]="synthetic refusal containing fake-sensitive-text"
    return httpx.Response(200,json={"choices":[{"finish_reason":"length" if mode=="incomplete" else "stop","message":message}],
        "usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15,"unknown":"never stored"}})


def perform(s,run,mode="ok"):
    return run_extraction(s.factory,run["job_id"],s.settings,httpx.MockTransport(lambda r:response_for(r,mode)))


def test_extract_then_edit_import_is_draft_and_idempotent(environment):
    s=configured(environment); run=enqueue(s)
    assert run["status"]=="QUEUED" and s.get("/requirements")[0]["requirement_id"]==s.req["requirement_id"]
    assert perform(s,run)["status"]=="SUCCEEDED"
    state=s.get(f"/extraction-runs/{run['id']}")
    assert state["completed_batch_count"]==1 and state["usage"]["total_tokens"]==15
    candidate=s.get("/requirement-candidates")[0]
    assert candidate["sources"][0]["quote"]=="Respond within 2 hours"
    proposed=copy.deepcopy(candidate["proposed"])
    decision={"expected_version":1,"action":"IMPORT","note":"构造验收：人工编辑标题后采纳。",
        "requirement":{"title":"人工核对后的响应承诺","text":"接报后2小时内响应。","category":"TECHNICAL","priority":"MANDATORY"}}
    key=str(uuid.uuid4())
    imported=s.post(f"/requirement-candidates/{candidate['id']}/decisions",decision,key=key).json()
    assert s.post(f"/requirement-candidates/{candidate['id']}/decisions",decision,key=key).json()==imported
    assert imported["proposed"]==proposed and imported["status"]=="IMPORTED" and imported["version"]==2
    requirements=s.get("/requirements")
    new=next(r for r in requirements if r["requirement_id"]==imported["requirement_id"])
    assert len(requirements)==2 and new["status"]=="DRAFT" and new["confirmed_by"] is None
    workspace=s.get("/workspace")
    assert workspace["current_baseline_id"] is None and workspace["review_epoch"]==0
    s.post(f"/requirement-candidates/{candidate['id']}/decisions",decision,status=409)
    # A second model run may repeat a candidate, but import cannot duplicate same text/source.
    second=enqueue(s);perform(s,second)
    repeated=s.get(f"/requirement-candidates?run_id={second['id']}")[0]
    s.post(f"/requirement-candidates/{repeated['id']}/decisions",decision,status=409)


@pytest.mark.parametrize("mode,code",[("bad_source","MODEL_SOURCE_INVALID"),("duplicate_source","MODEL_SOURCE_INVALID"),
    ("bad_shape","MODEL_OUTPUT_INVALID"),("refusal","MODEL_REFUSED"),("incomplete","MODEL_OUTPUT_INCOMPLETE")])
def test_untrusted_model_outputs_fail_closed(environment,mode,code):
    s=configured(environment);run=enqueue(s)
    result=perform(s,run,mode)
    assert result["error_code"]==code
    state=s.get(f"/extraction-runs/{run['id']}")
    assert state["status"]=="FAILED" and "fake-sensitive-text" not in state["error_detail"]
    assert s.get("/requirement-candidates")==[]
    with s.factory() as db:
        assert db.get(m.DocumentRevision,s.tender["revision_id"]).status=="NEEDS_REVIEW"


def test_configuration_quality_scope_and_role_guards(environment):
    s=configured(environment)
    config=s.client.get("/api/v1/extraction/config").json()
    assert "synthetic-test-key" not in json.dumps(config) and config["configured"]
    body={"artifact_id":s.tender["artifact_id"],"pages":[1],"expected_config_fingerprint":config["config_fingerprint"],"acknowledge_external_processing":True}
    s.post("/extraction-runs",body,who="reviewer",status=403)
    s.post("/extraction-runs",{**body,"acknowledge_external_processing":False},status=422)
    s.post("/extraction-runs",{**body,"pages":[1,1]},status=422)
    s.post("/extraction-runs",{**body,"artifact_id":s.response["artifact_id"]},status=422)
    s.post("/extraction-runs",{**body,"expected_config_fingerprint":"0"*64},status=409)
    s.settings.llm_enabled=False
    assert s.client.get("/api/v1/extraction/config").json()["configured"] is False
    s.post("/extraction-runs",body,status=503)
    s.settings.llm_enabled=True
    run=enqueue(s)
    s.post("/extraction-runs",body,status=409)
    outsider={"X-API-Key":"outsider-test-api-key-long"}
    assert s.client.get(s.root+f"/extraction-runs/{run['id']}",headers=outsider).status_code==404
    # New quality opinion invalidates queued input before any provider call.
    s.client.post(f"/api/v1/artifacts/{s.tender['artifact_id']}/pages/1/quality-reviews",
        json={"expected_version":1,"expected_diagnostic_profile":"text-quality-v1","decision":"NEEDS_REPROCESS","note":"构造变更"},
        headers={**s.auth(),"Idempotency-Key":str(uuid.uuid4())})
    assert perform(s,run)["error_code"]=="EXTRACTION_INPUT_CHANGED"


def test_checkpoint_retry_calls_only_unfinished_batches(environment):
    s=configured(environment);run=enqueue(s)
    with s.factory.begin() as db:
        record=db.get(m.ExtractionRun,run["id"])
        # Fault-injection setup: two valid batches with the same source tests checkpoint/dedup.
        record.batches=[copy.deepcopy(record.batches[0]),copy.deepcopy(record.batches[0])]
    calls=[]
    def temporarily_failing(request):
        calls.append(request.headers["Idempotency-Key"])
        return response_for(request) if len(calls)==1 else httpx.Response(429,json={"error":"fake-secret-provider-body"})
    result=run_extraction(s.factory,run["job_id"],s.settings,httpx.MockTransport(temporarily_failing))
    assert result["error_code"]=="MODEL_TRANSIENT"
    current=s.get(f"/extraction-runs/{run['id']}")
    assert current["status"]=="RETRY_WAIT" and current["completed_batch_count"]==1
    assert s.get("/requirement-candidates")==[]
    with s.factory.begin() as db: db.get(m.Job,run["job_id"]).next_attempt_at=m.utcnow()-timedelta(seconds=1)
    recover_jobs(s.factory,s.settings)
    resumed=[]
    def success(request):resumed.append(request.headers["Idempotency-Key"]);return response_for(request)
    assert run_extraction(s.factory,run["job_id"],s.settings,httpx.MockTransport(success))["status"]=="SUCCEEDED"
    assert len(resumed)==1 and resumed[0]==calls[1]
    assert len(s.get("/requirement-candidates"))==1


def test_inflight_cancel_fences_result_and_stale_candidate_cannot_import(environment):
    s=configured(environment);run=enqueue(s)
    def cancelling(request):
        s.post(f"/extraction-runs/{run['id']}/cancel",{"expected_attempt":1})
        return response_for(request)
    assert run_extraction(s.factory,run["job_id"],s.settings,httpx.MockTransport(cancelling))["status"]=="STALE_LEASE"
    assert s.get(f"/extraction-runs/{run['id']}")["status"]=="CANCELLED" and s.get("/requirement-candidates")==[]
    second=enqueue(s);perform(s,second)
    candidate=s.get("/requirement-candidates")[0]
    s.upload("TENDER","Changed tender within 1 hour",s.tender["document_id"])
    decision={"expected_version":1,"action":"IMPORT","note":"test","requirement":{
        k:candidate["proposed"][k] for k in ("title","text","category","priority")}}
    s.post(f"/requirement-candidates/{candidate['id']}/decisions",decision,status=409)
    s.post(f"/requirement-candidates/{candidate['id']}/decisions",{"expected_version":1,"action":"REJECT","note":"输入过期"})


def test_manual_retry_and_lease_expiry_do_not_break_pdf_state(environment):
    s=configured(environment);run=enqueue(s)
    run_extraction(s.factory,run["job_id"],s.settings,httpx.MockTransport(lambda request:httpx.Response(401,json={"secret":"not logged"})))
    s.post(f"/extraction-runs/{run['id']}/retry",{"expected_attempt":1})
    assert perform(s,run)["status"]=="SUCCEEDED"
    another=enqueue(s)
    with s.factory.begin() as db:
        job=db.get(m.Job,another["job_id"]);job.status="RUNNING";job.attempt=s.settings.job_max_attempts
        job.lease_until=m.utcnow()-timedelta(seconds=1)
    recover_jobs(s.factory,s.settings)
    with s.factory() as db:
        assert db.get(m.Job,another["job_id"]).status=="FAILED"
        assert db.get(m.DocumentRevision,s.tender["revision_id"]).status=="NEEDS_REVIEW"


def test_model_endpoint_credentials_cannot_be_embedded_in_url(environment):
    _,_,settings=environment
    settings.llm_enabled=True;settings.llm_model="synthetic";settings.llm_api_key=SecretStr("dummy")
    for url in ("https://key@example.com/v1","https://example.com/v1?key=secret","http://example.com/v1"):
        settings.llm_base_url=url
        with pytest.raises(ExtractionError):config_snapshot(settings)


def test_extraction_job_never_replaces_pdf_job_in_workspace_or_reupload(environment):
    s=configured(environment);run=enqueue(s)
    for mode in (None,"refusal"):
        if mode:perform(s,run,mode)
        document=next(d for d in s.get("/workbench")["documents"] if d["id"]==s.tender["document_id"])
        revision=document["revisions"][0]
        assert revision["artifact_id"]==s.tender["artifact_id"]
        assert revision["job_id"]==s.tender["job_id"] and revision["job_status"]=="SUCCEEDED"
        reused=s.client.post(f"/api/v1/documents/{s.tender['document_id']}/revisions",
            files={"file":("same.pdf",minimal_pdf("Respond within 2 hours"),"application/pdf")},
            headers={**s.auth(),"Idempotency-Key":str(uuid.uuid4())})
        assert reused.status_code==202 and reused.json()["reused"]
        assert reused.json()["job_id"]==s.tender["job_id"]
