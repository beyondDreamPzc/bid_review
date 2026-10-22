"""Milvus REST v2 adapter. No document text or remote error bodies in errors/logs."""
import json

import httpx
from app.storage import sha256

COLLECTION = "bid_formal_bm25_v1"


class RetrievalUnavailable(RuntimeError):
    pass


class Milvus:
    def __init__(self, settings):
        self.collection=COLLECTION
        self.url = settings.milvus_url.rstrip("/")
        self.token = settings.milvus_token.get_secret_value()

    def call(self, operation, **body):
        try:
            headers = {"Request-Timeout": "20"}
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
            with httpx.Client(timeout=25, trust_env=False, follow_redirects=False) as client:
                result = client.post(self.url + "/v2/vectordb/" + operation,
                    json={"collectionName": self.collection, **body}, headers=headers)
                result.raise_for_status()
                payload = result.json()
                if payload.get("code") != 0:
                    raise ValueError("Milvus operation failed")
                return payload.get("data")
        except (httpx.HTTPError, ValueError, TypeError) as error:
            raise RetrievalUnavailable("检索服务暂不可用，请稍后重试或重建索引。") from None

    def ensure(self):
        if self.call("collections/has")["has"]:
            return
        fields = [{"fieldName": "id", "dataType": "VarChar", "isPrimary": True,
                   "elementTypeParams": {"max_length": "100"}}]
        for name, length in (("project", 36), ("generation", 80), ("chunk", 64)):
            fields.append({"fieldName": name, "dataType": "VarChar",
                           "elementTypeParams": {"max_length": str(length)}})
        fields.extend([
            {"fieldName": "text", "dataType": "VarChar", "elementTypeParams": {
                "max_length": "8192", "enable_analyzer": "true",
                "analyzer_params": json.dumps({"type": "chinese"})}},
            {"fieldName": "sparse", "dataType": "SparseFloatVector"}])
        self.call("collections/create", schema={"autoId": False, "enableDynamicField": False,
            "fields": fields, "functions": [{"name": "text_bm25", "type": "BM25",
                "inputFieldNames": ["text"], "outputFieldNames": ["sparse"], "params": {}}]},
            indexParams=[{"fieldName": "sparse", "indexName": "sparse_bm25",
                "metricType": "BM25", "indexType": "SPARSE_INVERTED_INDEX",
                "params": {"inverted_index_algo": "DAAT_MAXSCORE", "bm25_k1": "1.2", "bm25_b": "0.75"}}],
            consistencyLevel="Strong")

    def write(self, project_id, generation, chunks):
        rows = [{"id": sha256(f"{generation}:{c.id}".encode()), "project": project_id, "generation": generation,
                 "chunk": c.id, "text": c.text} for c in chunks]
        self.call("entities/upsert", data=rows)

    def search(self, project_id, generation, query, limit):
        # Both values are server-selected. JSON encoding also prevents expression injection.
        predicate = f"project == {json.dumps(project_id)} and generation == {json.dumps(generation)}"
        return self.call("entities/search", data=[query], annsField="sparse", filter=predicate,
            limit=limit, outputFields=["chunk"], consistencyLevel="Strong",
            searchParams={"metricType": "BM25", "params": {"drop_ratio_search": 0}})
