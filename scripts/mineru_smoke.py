"""真实HTTP/MySQL/Celery/MinerU验收，只使用仓库构造样本。"""
import json
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.jobs import run_job
from app.models import ParseArtifact,User
from app.mineru_parser import DEFAULT_PROFILE
from app.services import ingest_pdf
from app.storage import BlobStore,sha256


def main():
    settings=get_settings()
    assert settings.parser_profile==DEFAULT_PROFILE,"Run against the default real MinerU profile"
    token=secrets.token_urlsafe(32)
    with SessionLocal.begin() as db:
        user=User(name="MinerU构造验收-"+uuid.uuid4().hex[:8],api_key_hash=sha256(token.encode()))
        db.add(user);db.flush();uid=user.id
    with httpx.Client(base_url="http://localhost:8000",headers={"X-API-Key":token},timeout=30) as client:
        def post(route,body,key=None,status=200):
            response=client.post(route,json=body,headers={"Idempotency-Key":key or str(uuid.uuid4())})
            assert response.status_code==status,response.text
            return response.json()
        def get(route):
            response=client.get(route);response.raise_for_status();return response.json()
        def wait(job):
            for _ in range(1000):
                state=get(f"/api/v1/jobs/{job}")
                if state["status"]=="SUCCEEDED":return state["artifact_id"]
                assert state["status"]!="FAILED",state
                time.sleep(1)
            raise TimeoutError("MinerU queue did not finish within test budget")
        pid=post("/api/v1/projects",{"name":"MinerU真实引擎验收 · 构造文件"},status=201)["id"]
        prefix=f"/api/v1/projects/{pid}"
        tender=(Path(__file__).resolve().parent.parent/"app/demo_assets/tender.pdf").read_bytes()
        # Seed one historical engine artifact, then upgrade the very same bytes through the public API.
        with SessionLocal() as db:
            old=ingest_pdf(db,BlobStore(settings.storage_path),db.get(User,uid),pid,tender,
                "构造招标 · 历史探针","TENDER",str(uuid.uuid4()),"pdfplumber-probe-v1")
        historical=run_job(SessionLocal,old["job_id"],settings)["artifact_id"]
        old_blocks=get(f"/api/v1/artifacts/{historical}/blocks?page=2")
        ref=next(b for b in old_blocks if "响应时限" in b["text"])
        old_source=get(f"/api/v1/artifacts/{historical}/blocks/{ref['block_id']}/source")
        requirement=post(prefix+"/requirements",{"title":"构造历史要求","text":"接报后2小时内响应。",
            "category":"TECHNICAL","priority":"GENERAL","sources":[{"artifact_id":historical,"block_id":ref["block_id"]}]},status=201)
        key=str(uuid.uuid4());route=f"/api/v1/revisions/{old['revision_id']}/parse"
        with ThreadPoolExecutor(max_workers=4) as pool:
            submissions=list(pool.map(lambda _:post(route,{},key,status=202),range(4)))
        assert all(s==submissions[0] for s in submissions)
        aid=wait(submissions[0]["job_id"])
        artifact=get(f"/api/v1/artifacts/{aid}")
        assert artifact["parser_profile"]==DEFAULT_PROFILE and artifact["page_count"]==3 and aid!=historical
        blocks=get(f"/api/v1/artifacts/{aid}/blocks?page=2")
        all_text="".join(b["text"] for b in blocks)
        assert "2小时" in all_text and "2次" in all_text
        assert get(f"/api/v1/artifacts/{historical}/blocks/{ref['block_id']}/source")==old_source
        assert get(prefix+"/requirements")[0]["sources"][0]["artifact_id"]==historical
        assert get(f"/api/v1/artifacts/{aid}/quality")["reviewed_page_count"]==0
        workspace=get(prefix+"/workbench")
        assert workspace["documents"][0]["revisions"][0]["artifact_id"]==aid
        assert workspace["workspace"]["review_epoch"]==0
        with SessionLocal() as db:
            records=db.scalars(select(ParseArtifact).where(ParseArtifact.revision_id==old["revision_id"])).all()
            assert len(records)==2
            parsed=json.loads(BlobStore(settings.storage_path).read(db.get(ParseArtifact,aid).storage_key))
        summary={"engine":"REAL_MINERU_SDK","profile":DEFAULT_PROFILE,"runtime":parsed["mineru"]["runtime"],
            "actual":parsed["mineru"]["actual"],"pages":artifact["page_count"],"blocks":artifact["block_count"],
            "parallel_reparse_requests":4,"artifacts_on_same_pdf":2,"old_source_unchanged":True,"quality_not_inherited":True}
        # New uploads also use MinerU, rather than only the reparse path.
        response=client.post(prefix+"/documents",data={"title":"构造响应 · 新上传","kind":"RESPONSE"},
            files={"file":("response.pdf",tender,"application/pdf")},headers={"Idempotency-Key":str(uuid.uuid4())})
        assert response.status_code==202,response.text
        new_id=wait(response.json()["job_id"])
        assert get(f"/api/v1/artifacts/{new_id}")["parser_profile"]==DEFAULT_PROFILE
        summary["new_upload_uses_mineru"]=True
        print(json.dumps(summary,ensure_ascii=False))


if __name__=="__main__":main()
