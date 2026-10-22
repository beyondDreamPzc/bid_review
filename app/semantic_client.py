import math
import httpx
from app.milvus import RetrievalUnavailable

PROFILE="bge-zh-small-int8-bge-reranker-base-int8-v1"


class Semantic:
    def __init__(self,settings):
        self.url=settings.semantic_url.rstrip("/")

    def call(self,path,**body):
        try:
            with httpx.Client(timeout=90,trust_env=False,follow_redirects=False) as client:
                response=client.post(self.url+path,json={"profile":PROFILE,**body})
                response.raise_for_status();data=response.json()
                if data.get("profile")!=PROFILE:raise ValueError()
                return data
        except (httpx.HTTPError,ValueError,TypeError):
            raise RetrievalUnavailable("本地语义模型暂不可用，请检查模型服务后重试；未自动降级为关键词检索。") from None

    def embed(self,texts,query=False):
        vectors=self.call("/embed",texts=texts,query=query)["vectors"]
        if len(vectors)!=len(texts) or any(len(v)!=512 or not all(math.isfinite(x) for x in v) for v in vectors):
            raise RetrievalUnavailable("语义向量格式校验失败。")
        return vectors

    def rank(self,query,texts):
        scores=self.call("/rerank",query=query,texts=texts)["scores"]
        if len(scores)!=len(texts) or not all(math.isfinite(x) for x in scores):
            raise RetrievalUnavailable("重排分数格式校验失败。")
        return scores


def reciprocal_rank_fusion(lists,k=60):
    scores={}
    for hits in lists:
        seen=set()
        for rank,hit in enumerate(hits,1):
            chunk=hit["chunk"]
            if chunk in seen:continue
            seen.add(chunk);scores[chunk]=scores.get(chunk,0)+1/(k+rank)
    return sorted(scores.items(),key=lambda pair:(-pair[1],pair[0]))
