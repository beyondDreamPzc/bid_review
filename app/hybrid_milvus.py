"""Versioned dense+sparse projection; rank fusion/reranking stay explicit and inspectable."""
import json
from app.milvus import Milvus
from app.semantic_client import Semantic,reciprocal_rank_fusion
from app.storage import sha256


class HybridMilvus(Milvus):
    def __init__(self,settings):
        super().__init__(settings)
        self.collection="bid_formal_hybrid_bge_v1"
        self.semantic=Semantic(settings)

    def ensure(self):
        if self.call("collections/has")["has"]:return
        fields=[{"fieldName":"id","dataType":"VarChar","isPrimary":True,
            "elementTypeParams":{"max_length":"100"}}]
        for name,length in (("project",36),("generation",80),("chunk",64)):
            fields.append({"fieldName":name,"dataType":"VarChar","elementTypeParams":{"max_length":str(length)}})
        fields.extend([
            {"fieldName":"text","dataType":"VarChar","elementTypeParams":{"max_length":"8192",
                "enable_analyzer":"true","analyzer_params":json.dumps({"type":"chinese"})}},
            {"fieldName":"sparse","dataType":"SparseFloatVector"},
            {"fieldName":"dense","dataType":"FloatVector","elementTypeParams":{"dim":"512"}}])
        self.call("collections/create",schema={"autoId":False,"enableDynamicField":False,"fields":fields,
            "functions":[{"name":"text_bm25","type":"BM25","inputFieldNames":["text"],"outputFieldNames":["sparse"],"params":{}}]},
            indexParams=[{"fieldName":"sparse","indexName":"sparse_bm25","metricType":"BM25",
                "indexType":"SPARSE_INVERTED_INDEX","params":{"inverted_index_algo":"DAAT_MAXSCORE"}},
                {"fieldName":"dense","indexName":"dense_cosine","metricType":"COSINE","indexType":"HNSW",
                    "params":{"M":"16","efConstruction":"200"}}],consistencyLevel="Strong")

    def write(self,project_id,generation,chunks):
        vectors=self.semantic.embed([c.text for c in chunks])
        rows=[{"id":sha256(f"{generation}:{c.id}".encode()),"project":project_id,"generation":generation,
            "chunk":c.id,"text":c.text,"dense":vector} for c,vector in zip(chunks,vectors,strict=True)]
        self.call("entities/upsert",data=rows)

    def search(self,project_id,generation,query,limit):
        vector=self.semantic.embed([query],query=True)[0]
        predicate=f"project == {json.dumps(project_id)} and generation == {json.dumps(generation)}"
        sparse=super().search(project_id,generation,query,30)
        dense=self.call("entities/search",data=[vector],annsField="dense",filter=predicate,limit=30,
            outputFields=["chunk"],consistencyLevel="Strong",searchParams={"metricType":"COSINE","params":{"ef":80}})
        return [{"chunk":chunk,"distance":score} for chunk,score in reciprocal_rank_fusion([sparse,dense])[:30]]
