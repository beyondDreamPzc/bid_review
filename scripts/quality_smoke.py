"""通过实际 HTTP/MySQL/Redis/Worker 验证质量记录与新产物隔离。"""
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
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import PageQualityReview, User
from app.quality import PROFILE
from app.storage import sha256


def main():
    key=secrets.token_urlsafe(36)
    with SessionLocal.begin() as db:
        assert db.bind.dialect.name=="mysql", "Run in the Compose MySQL environment"
        db.add(User(name="synthetic-quality-owner",api_key_hash=sha256(key.encode())))
    with httpx.Client(base_url="http://localhost:8000",trust_env=False,timeout=30) as client:
        headers={"Origin":"http://localhost:8000"}
        assert client.post("/api/v1/auth/session",json={"api_key":key},headers=headers).status_code==200
        def post(path,body=None,status=201,request_key=None,**kwargs):
            response=client.post(path,json=body,headers={**headers,"Idempotency-Key":request_key or str(uuid.uuid4())},**kwargs)
            assert response.status_code==status, f"HTTP {response.status_code}: {response.text}"
            return response.json()
        pid=post("/api/v1/projects",{"name":"Synthetic extraction quality workflow"})["id"]
        def upload(asset,document_id=None):
            route=f"/api/v1/documents/{document_id}/revisions" if document_id else f"/api/v1/projects/{pid}/documents"
            uploaded=post(route,status=202,data={} if document_id else {"title":"Synthetic response PDF","kind":"RESPONSE"},
                files={"file":("synthetic.pdf",(ROOT/"app"/"demo_assets"/asset).read_bytes(),"application/pdf")})
            for _ in range(90):
                job=client.get("/api/v1/jobs/"+uploaded["job_id"]).json()
                if job["status"]=="SUCCEEDED":
                    return uploaded,job["artifact_id"]
                assert job["status"]!="FAILED", "Worker rejected the test fixture"
                time.sleep(1)
            raise TimeoutError("Real worker did not finish")
        original,aid=upload("response-2h.pdf")
        url=f"/api/v1/artifacts/{aid}"
        report=client.get(url+"/quality").json()
        assert report["page_count"]==3 and report["reviewed_page_count"]==0
        blocks=client.get(url+"/blocks").json()
        body={"expected_version":0,"expected_diagnostic_profile":PROFILE,"decision":"TEXT_USABLE",
              "note":"构造集成测试：模拟人工打开原件核对，不代表真实业务人工结论。"}
        request_key=str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(lambda _:post(url+"/pages/1/quality-reviews",body,request_key=request_key),range(4)))
        assert all(row==replies[0] for row in replies)
        post(url+"/pages/1/quality-reviews",body,status=409)
        post(url+"/pages/1/quality-reviews",{**body,"expected_version":1,"decision":"NEEDS_REPROCESS",
            "note":"构造验收：保留原意见，记录仍需处理。"})
        assert [r["version"] for r in client.get(url+"/pages/1/quality-reviews").json()]==[2,1]
        changed,new_aid=upload("response-2h-v3.pdf",original["document_id"])
        assert changed["revision_no"]==2 and new_aid!=aid
        assert client.get(f"/api/v1/artifacts/{new_aid}/quality").json()["reviewed_page_count"]==0
        assert client.get(url+"/blocks").json()==blocks
        assert client.get(f"/api/v1/projects/{pid}/workspace").json()["review_epoch"]==0
        with SessionLocal() as db:
            assert db.scalar(select(func.count()).select_from(PageQualityReview).where(PageQualityReview.artifact_id==aid))==2
        assert client.delete("/api/v1/auth/session",headers=headers).status_code==200
        assert client.get(url+"/quality").status_code==401
        print(json.dumps({"database":"mysql","queue":"redis/celery","sample_type":"SYNTHETIC",
            "parallel_same_key_requests":4,"unique_first_review":1,"history_versions":[2,1],
            "new_artifact_review_count":0,"source_blocks_unchanged":True,"business_epoch_unchanged":True}))


if __name__=="__main__":
    main()
