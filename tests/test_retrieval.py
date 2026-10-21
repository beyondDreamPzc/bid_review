from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from app import models as m, retrieval as r
from app.jobs import recover_jobs
from app.milvus import Milvus, RetrievalUnavailable
from app.retrieval_api import SearchInput
from tests.test_business import Scenario


class Projection:
    def __init__(self):
        self.rows = []

    def ensure(self):
        pass

    def write(self, project_id, generation, chunks):
        self.rows += [(project_id, generation, c.id) for c in chunks]

    def search(self, project_id, generation, query, limit):
        return [{"chunk": chunk, "distance": 1.2} for project, gen, chunk in self.rows
                if project == project_id and gen == generation][:limit]


@pytest.fixture
def setup(environment, monkeypatch):
    x = Scenario(environment)
    x.settings.retrieval_enabled = True
    x.material = x.materials()
    x.index_body = {"expected_material_set_id": x.material["id"]}
    x.projection = Projection()
    monkeypatch.setattr(r, "Milvus", lambda _: x.projection)
    return x


def build(x):
    item = x.post("/retrieval/indexes", x.index_body, status=202).json()
    assert r.run_index(x.factory, item["job_id"], x.settings, x.projection)["status"] == "SUCCEEDED"
    return item


def test_formal_only_immutable_sources_and_idempotency(setup):
    x = setup
    reference = x.upload("EVIDENCE", "Secret reference only")
    x.material = x.materials(extra=[{"artifact_id": reference["artifact_id"], "submission_role": "REFERENCE"}])
    x.index_body = {"expected_material_set_id": x.material["id"]}
    item = build(x)
    assert x.post("/retrieval/indexes", x.index_body, status=202).json()["id"] == item["id"]
    result = x.post("/retrieval/search", {**x.index_body, "query": "4 hours"}, who="reader").json()
    assert len(result["results"]) == 1
    hit = result["results"][0]
    assert hit["quote"] == "Respond within 4 hours"
    assert hit["source"]["artifact_id"] == x.response["artifact_id"]
    assert hit["source"]["submission_role"] == "FORMAL_RESPONSE"
    assert hit["original_url"].endswith("#page=1")
    with x.factory() as db:
        assert db.scalar(select(func.count()).select_from(m.RetrievalIndex)) == 1
        assert db.get(m.DocumentRevision, x.response["revision_id"]).status == "NEEDS_REVIEW"


def test_permissions_input_validation_and_disabled(setup):
    x = setup
    x.post("/retrieval/indexes", x.index_body, who="reader", status=403)
    x.post("/retrieval/indexes", {"expected_material_set_id": m.uid()}, status=409)
    x.post("/retrieval/search", {**x.index_body, "query": " "}, status=422)
    x.post("/retrieval/search", {**x.index_body, "query": "hours"}, status=409)
    x.settings.retrieval_enabled = False
    x.post("/retrieval/indexes", x.index_body, status=503)
    x.settings.retrieval_enabled = True
    outsider = {"X-API-Key": "outsider-test-api-key-long"}
    assert x.client.get(x.root + "/retrieval", headers=outsider).status_code == 404
    assert x.client.post(x.root + "/retrieval/search", json={**x.index_body,"query":"hours"},headers=outsider).status_code == 404


def test_new_material_requires_new_index_even_when_upload_is_same(setup):
    x = setup
    old = build(x)
    x.material = x.materials()
    x.post("/retrieval/search", {**x.index_body, "query": "hours"}, status=409)
    x.index_body = {"expected_material_set_id": x.material["id"]}
    x.post("/retrieval/search", {**x.index_body, "query": "hours"}, status=409)
    new = build(x)
    assert old["id"] != new["id"]
    assert x.post("/retrieval/search", {**x.index_body,"query":"hours"}).json()["index_id"] == new["id"]


@pytest.mark.parametrize("change", ["material", "member", "rebuild"])
def test_input_or_permission_changes_during_network_are_rejected(setup, change):
    x = setup
    item = build(x)
    original = x.projection.search
    def race(*args):
        hits = original(*args)
        with x.factory.begin() as db:
            if change == "material":
                db.get(m.Project, x.project).current_material_set_id = None
            elif change == "member":
                db.delete(db.get(m.ProjectMember, (x.project, x.ids["reader"])))
            else:
                db.get(m.RetrievalIndex, item["id"]).published_token = None
        return hits
    x.projection.search = race
    x.post("/retrieval/search", {**x.index_body,"query":"hours"}, who="reader", status=404 if change=="member" else 409)


def test_untrusted_projection_cannot_supply_foreign_or_modified_text(setup):
    x = setup
    item = build(x)
    x.projection.search = lambda *args: [{"chunk":"foreign-chunk", "distance":100}]
    x.post("/retrieval/search", {**x.index_body,"query":"hours"}, status=503)
    with x.factory.begin() as db:
        chunk = db.scalar(select(m.RetrievalChunk).where(m.RetrievalChunk.index_id==item["id"]))
        chunk_id=chunk.id
        block=db.get(m.DocumentBlock,(chunk.source["artifact_id"],chunk.source["block_id"]))
        block.text="Tampered text"
    x.projection.search = lambda *args: [{"chunk":chunk_id,"distance":1}]
    x.post("/retrieval/search", {**x.index_body,"query":"hours"}, status=503)


def test_partial_write_and_expired_lease_cannot_publish(setup):
    x = setup
    item = x.post("/retrieval/indexes", x.index_body, status=202).json()
    def late(*args):
        with x.factory.begin() as db:
            db.get(m.Job,item["job_id"]).lease_token += 1
    x.projection.write = late
    assert r.run_index(x.factory,item["job_id"],x.settings,x.projection)["status"] == "STALE_LEASE"
    with x.factory.begin() as db:
        assert db.get(m.RetrievalIndex,item["id"]).published_token is None
        job=db.get(m.Job,item["job_id"])
        job.lease_until=m.utcnow()-timedelta(seconds=1)
        job.attempt=x.settings.job_max_attempts
    recover_jobs(x.factory,x.settings)
    with x.factory() as db:
        assert db.get(m.Job,item["job_id"]).status == "FAILED"
        assert db.get(m.DocumentRevision,x.response["revision_id"]).status == "NEEDS_REVIEW"


def test_failure_retry_and_explicit_rebuild_use_new_generation(setup):
    x = setup
    item = x.post("/retrieval/indexes",x.index_body,status=202).json()
    with x.factory.begin() as db:
        db.get(m.Job,item["job_id"]).attempt=x.settings.job_max_attempts-1
    def fail():
        raise RuntimeError("private-url-and-document-text")
    x.projection.ensure=fail
    assert r.run_index(x.factory,item["job_id"],x.settings,x.projection)["status"] == "FAILED_OR_RETRY_WAIT"
    assert "private" not in x.get("/retrieval")["error_detail"]
    x.post("/retrieval/indexes",{**x.index_body,"retry_failed":True},status=202)
    x.projection.ensure=lambda:None
    assert r.run_index(x.factory,item["job_id"],x.settings,x.projection)["status"] == "SUCCEEDED"
    first=x.projection.rows[-1][1]
    x.post("/retrieval/indexes",{**x.index_body,"rebuild":True},status=202)
    x.post("/retrieval/search",{**x.index_body,"query":"hours"},status=409)
    assert r.run_index(x.factory,item["job_id"],x.settings,x.projection)["status"] == "SUCCEEDED"
    assert x.projection.rows[-1][1]!=first


def test_chunk_offsets_exact_overlap_and_no_empty_or_cross_block(setup):
    x = setup
    with x.factory.begin() as db:
        block=db.get(m.DocumentBlock,(x.response["artifact_id"],x.response["block_id"]))
        block.text="甲"*2500;block.text_hash=r.sha256(block.text.encode())
    build(x)
    with x.factory() as db:
        chunks=db.scalars(select(m.RetrievalChunk)).all()
        assert sorted((c.source["start"],c.source["end"]) for c in chunks)==[(0,1200),(1080,2280),(2160,2500)]
        assert all(c.text=="甲"*(c.source["end"]-c.source["start"]) for c in chunks)


def test_milvus_adapter_filters_escaped_server_scope_and_redacts_errors(monkeypatch):
    requests=[]
    def handle(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={"code":0,"data":[]})
    actual=httpx.Client
    monkeypatch.setattr("app.milvus.httpx.Client",lambda **kw:actual(transport=httpx.MockTransport(handle)))
    client=Milvus(SimpleNamespace(milvus_url="http://local",milvus_token=SimpleNamespace(get_secret_value=lambda:"")))
    assert client.search('p"',"generation",'query " or true',3)==[]
    assert requests[0]["data"]==['query " or true']
    assert requests[0]["filter"]=='project == "p\\\"" and generation == "generation"'
    def unavailable(request):
        return httpx.Response(200,json={"code":100,"message":"private secret"})
    monkeypatch.setattr("app.milvus.httpx.Client",lambda **kw:actual(transport=httpx.MockTransport(unavailable)))
    with pytest.raises(RetrievalUnavailable,match="检索服务") as error:
        client.search("p","g","q",3)
    assert "private" not in str(error.value)
