"""Real MySQL/outbox/Redis/Celery/MinerU/Milvus integration; synthetic repository PDFs only."""
import json
import secrets
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.models import RetrievalChunk, User
from app.storage import sha256


def main():
    token = secrets.token_urlsafe(32)
    with SessionLocal.begin() as db:
        db.add(User(name="正式材料检索验收-" + uuid.uuid4().hex[:8], api_key_hash=sha256(token.encode())))
    with httpx.Client(base_url="http://api:8000", headers={"X-API-Key": token}, timeout=35) as client:
        def post(path, body, status=200, key=None):
            response = client.post(path, json=body, headers={"Idempotency-Key":key or str(uuid.uuid4())})
            assert response.status_code == status, response.text
            return response.json()
        def get(path):
            response=client.get(path); response.raise_for_status(); return response.json()
        def wait(job):
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                state = get(f"/api/v1/jobs/{job}")
                if state["status"] == "SUCCEEDED": return state
                assert state["status"] != "FAILED", state
                time.sleep(1)
            raise TimeoutError("Integration job exceeded 240 seconds")
        pid = post("/api/v1/projects", {"name":"正式材料检索验收 · 构造响应"}, 201)["id"]
        root = f"/api/v1/projects/{pid}"
        def upload(name, kind="RESPONSE", document=None):
            path = f"/api/v1/documents/{document}/revisions" if document else root+"/documents"
            content=(Path(__file__).resolve().parent.parent/"app/demo_assets"/name).read_bytes()
            response=client.post(path, data={} if document else {"title":name,"kind":kind},
                files={"file":(name,content,"application/pdf")},headers={"Idempotency-Key":str(uuid.uuid4())})
            assert response.status_code==202,response.text
            item=response.json(); artifact=wait(item["job_id"])["artifact_id"]
            return {**item,"artifact_id":artifact}
        def materials(file, reference=None):
            workspace=get(root+"/workspace")
            items=[{"artifact_id":file["artifact_id"],"submission_role":"FORMAL_RESPONSE"}]
            if reference:items.append({"artifact_id":reference["artifact_id"],"submission_role":"REFERENCE"})
            return post(root+"/material-sets",{"expected_epoch":workspace["review_epoch"],
                "expected_current_material_set_id":workspace["current_material_set_id"],"items":items},201)
        old=upload("response-4h.pdf")
        reference=upload("tender.pdf","EVIDENCE")
        material=materials(old,reference)
        body={"expected_material_set_id":material["id"]}
        key=str(uuid.uuid4())
        with ThreadPoolExecutor(max_workers=4) as pool:
            submissions=list(pool.map(lambda _:post(root+"/retrieval/indexes",body,202,key),range(4)))
        assert all(s==submissions[0] for s in submissions)
        index=submissions[0];wait(index["job_id"])
        def query(body, text, status=200):
            return post(root+"/retrieval/search",{**body,"query":text,"limit":5},status)
        hits=query(body,"响应时限")
        assert any("4小时" in h["quote"] for h in hits["results"]),hits
        assert all(h["source"]["artifact_id"]==old["artifact_id"] for h in hits["results"])
        for hit in hits["results"]:
            s=hit["source"]
            original=get(f"/api/v1/artifacts/{s['artifact_id']}/blocks/{s['block_id']}/source")
            assert original["quote"][s["start"]:s["end"]]==hit["quote"]
        assert query(body,"xyznohitqwerty928475")["results"]==[]
        updated=upload("response-2h.pdf",document=old["document_id"])
        assert any("4小时" in h["quote"] for h in query(body,"响应时限")["results"])
        current=materials(updated)
        query(body,"响应时限",409)
        current_body={"expected_material_set_id":current["id"]}
        query(current_body,"响应时限",409)
        new=post(root+"/retrieval/indexes",current_body,202);wait(new["job_id"])
        result=query(current_body,"响应时限")
        assert any("2小时" in h["quote"] for h in result["results"]),result
        assert not any("4小时" in h["quote"] for h in result["results"])
        # Rebuild after projection loss uses a new fenced generation, with stable source facts.
        rebuilt=post(root+"/retrieval/indexes",{**current_body,"rebuild":True},202);wait(rebuilt["job_id"])
        assert query(current_body,"响应时限")["results"][0]["source"]["artifact_id"]==updated["artifact_id"]
        with SessionLocal() as db:
            chunks=db.scalars(select(RetrievalChunk).where(RetrievalChunk.index_id==new["id"])).all()
        print(json.dumps({"engine":"REAL_MILVUS_2.6.6_BM25","profile":result["profile"],
            "project_id":pid,"parallel_build_requests":4,"deduplicated_jobs":1,
            "chunks":len(chunks),"old_response":"4小时","new_response":"2小时",
            "reference_excluded":True,"upload_does_not_change_search":True,
            "new_material_invalidates_search":True,"exact_source_verified":True,
            "unknown_term_empty":True,"rebuild_succeeded":True},ensure_ascii=False))


if __name__=="__main__":main()
