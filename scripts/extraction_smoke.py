"""实际队列与合成模型 HTTP 服务的接口验收；不冒充真实模型效果。"""
import json
import secrets
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import httpx
from sqlalchemy import func,select
from app.database import SessionLocal
from app.models import Requirement,User
from app.storage import sha256


def main():
    key=secrets.token_urlsafe(36)
    with SessionLocal.begin() as db:
        assert db.bind.dialect.name=="mysql"
        db.add(User(name="synthetic-extraction-owner",api_key_hash=sha256(key.encode())))
    with httpx.Client(base_url="http://localhost:8000",trust_env=False,timeout=30) as client:
        origin={"Origin":"http://localhost:8000"}
        assert client.post("/api/v1/auth/session",json={"api_key":key},headers=origin).status_code==200
        def get(path):
            response=client.get(path);assert response.status_code==200,response.text;return response.json()
        def post(path,body=None,status=200,request_key=None,**kwargs):
            response=client.post(path,json=body,headers={**origin,"Idempotency-Key":request_key or str(uuid.uuid4())},**kwargs)
            assert response.status_code==status,f"HTTP {response.status_code}: {response.text}"
            return response.json()
        config=get("/api/v1/extraction/config")
        assert config["configured"] and config["model"]=="synthetic-contract-fixture", "Refusing to spend on a real model in this test"
        pid=post("/api/v1/projects",{"name":"Synthetic candidate extraction contract"},201)["id"]
        prefix=f"/api/v1/projects/{pid}"
        upload=post(prefix+"/documents",status=202,data={"title":"Synthetic tender","kind":"TENDER"},
            files={"file":("synthetic.pdf",(ROOT/"app/demo_assets/tender.pdf").read_bytes(),"application/pdf")})
        for _ in range(90):
            job=get("/api/v1/jobs/"+upload["job_id"])
            if job["status"]=="SUCCEEDED":break
            assert job["status"]!="FAILED";time.sleep(1)
        else:raise TimeoutError("Parser worker timeout")
        aid=job["artifact_id"]
        post(f"/api/v1/artifacts/{aid}/pages/2/quality-reviews",{"expected_version":0,
            "expected_diagnostic_profile":"text-quality-v1","decision":"TEXT_USABLE","note":"构造集成验收输入"},201)
        body={"artifact_id":aid,"pages":[2],"expected_config_fingerprint":config["config_fingerprint"],"acknowledge_external_processing":True}
        idem=str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=4) as pool:
            runs=list(pool.map(lambda _:post(prefix+"/extraction-runs",body,202,idem),range(4)))
        assert all(r==runs[0] for r in runs)
        run=runs[0]
        for _ in range(120):
            current=get(prefix+f"/extraction-runs/{run['id']}")
            if current["status"]=="SUCCEEDED":break
            assert current["status"]!="FAILED",current;time.sleep(1)
        else:raise TimeoutError("Extraction worker timeout")
        assert current["attempt"]==2,"Fixture's first 429 must exercise automatic retry"
        candidates=get(prefix+f"/requirement-candidates?run_id={run['id']}")
        assert len(candidates)==2
        first=candidates[0]
        decision={"expected_version":1,"action":"IMPORT","note":"合成接口验收：人工核对后采纳为草稿。",
            "requirement":{k:first["proposed"][k] for k in ("title","text","category","priority")}}
        idem=str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=4) as pool:
            imported=list(pool.map(lambda _:post(prefix+f"/requirement-candidates/{first['id']}/decisions",decision,request_key=idem),range(4)))
        assert all(r==imported[0] for r in imported)
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(Requirement).where(Requirement.project_id==pid))==1
        requirements=get(prefix+"/requirements")
        assert len(requirements)==1 and requirements[0]["status"]=="DRAFT" and requirements[0]["confirmed_by"] is None
        workspace=get(prefix+"/workspace")
        assert workspace["review_epoch"]==0 and workspace["current_baseline_id"] is None
        post(f"/api/v1/artifacts/{aid}/pages/2/quality-reviews",{"expected_version":1,
            "expected_diagnostic_profile":"text-quality-v1","decision":"NEEDS_REPROCESS","note":"构造输入变化测试"},201)
        remaining=candidates[1]
        post(prefix+f"/requirement-candidates/{remaining['id']}/decisions",{**decision,
            "requirement":{k:remaining["proposed"][k] for k in ("title","text","category","priority")}},409)
        assert get(prefix+f"/extraction-runs/{run['id']}")["freshness"]=="STALE"
        assert client.delete("/api/v1/auth/session",headers=origin).status_code==200
        print(json.dumps({"database":"mysql","queue":"redis/celery","model":"SYNTHETIC_HTTP_FIXTURE_NOT_REAL_AI",
            "model_attempts":2,"parallel_enqueue_requests":4,"candidate_count":2,
            "parallel_import_requests":4,"unique_requirement_count":1,"imported_status":"DRAFT",
            "baseline_not_auto_published":True,"stale_input_rejected":True}))


if __name__=="__main__":main()
