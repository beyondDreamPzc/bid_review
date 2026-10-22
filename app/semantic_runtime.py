"""Isolated, pinned ONNX CPU inference. No remote code, cloud API or business database access."""
import hashlib
import json
import os
from pathlib import Path
from functools import lru_cache
from threading import Lock

from fastapi import FastAPI,HTTPException
from pydantic import BaseModel,Field

ROOT=Path(__file__).resolve().parent.parent
MANIFEST=json.loads((ROOT/"config/semantic-models.json").read_text(encoding="utf-8"))
PROFILE=MANIFEST["profile"]
lock=Lock()
app=FastAPI(title="Local semantic inference",docs_url=None,redoc_url=None)


@lru_cache
def runtime(name):
    import onnxruntime as ort
    from tokenizers import Tokenizer
    folder=Path(os.environ.get("BID_SEMANTIC_MODELS_PATH","/data/semantic"))/name
    for relative,expected in MANIFEST[name]["files"].items():
        if hashlib.sha256((folder/relative).read_bytes()).hexdigest()!=expected:
            raise RuntimeError("Pinned model asset checksum mismatch")
    tokenizer=Tokenizer.from_file(str(folder/"tokenizer.json"))
    tokenizer.enable_truncation(max_length=512)
    tokenizer.enable_padding()
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(folder/"onnx/model_quantized.onnx"),sess_options=options,
        providers=["CPUExecutionProvider"])
    return tokenizer,session


def infer(name,texts):
    import numpy as np
    tokenizer,session=runtime(name)
    encoded=tokenizer.encode_batch(texts)
    feed={"input_ids":np.array([e.ids for e in encoded],dtype=np.int64),
          "attention_mask":np.array([e.attention_mask for e in encoded],dtype=np.int64),
          "token_type_ids":np.array([e.type_ids for e in encoded],dtype=np.int64)}
    return session.run(None,{item.name:feed[item.name] for item in session.get_inputs()})[0]


class EmbedInput(BaseModel):
    profile:str
    query:bool=False
    texts:list[str]=Field(min_length=1,max_length=100)


class RankInput(BaseModel):
    profile:str
    query:str=Field(min_length=1,max_length=400)
    texts:list[str]=Field(min_length=1,max_length=30)


@app.get("/health")
def health():
    try:
        runtime("embedding");runtime("reranker")
        return {"status":"ready","profile":PROFILE,"dimension":512}
    except Exception:
        raise HTTPException(503,"Local models are not ready") from None


@app.post("/embed")
def embed(body:EmbedInput):
    import numpy as np
    if body.profile!=PROFILE or any(not t.strip() or len(t)>450 for t in body.texts):
        raise HTTPException(422,"Profile mismatch or input exceeds 450 characters")
    texts=[("为这个句子生成表示以用于检索相关文章："+t) if body.query else t for t in body.texts]
    with lock:
        output=infer("embedding",texts)
    vectors=output[:,0,:] if output.ndim==3 else output
    vectors=vectors/np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-12)
    return {"profile":PROFILE,"vectors":vectors.tolist()}


@app.post("/rerank")
def rerank(body:RankInput):
    if body.profile!=PROFILE or any(not t.strip() or len(t)>450 for t in body.texts):
        raise HTTPException(422,"Profile mismatch or input exceeds 450 characters")
    with lock:
        output=infer("reranker",[(body.query,t) for t in body.texts])
    return {"profile":PROFILE,"scores":output.reshape(-1).tolist()}
