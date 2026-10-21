"""仅供合成 HTTP 契约验收，绝不是真实模型或运行时后备服务。无宿主机端口。"""
import json
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

calls=0
lock=Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass  # Do not log request text or Authorization.

    def send_json(self,status,value):
        raw=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)

    def do_GET(self):
        self.send_json(200,{"fixture":"SYNTHETIC_HTTP_CONTRACT_ONLY","calls":calls})

    def do_POST(self):
        global calls
        if self.path!="/v1/chat/completions" or self.headers.get("Authorization")!="Bearer synthetic-local-contract-token":
            return self.send_json(403,{"error":"Synthetic fixture only"})
        size=int(self.headers.get("Content-Length","0"))
        if not 0<size<256000:return self.send_json(413,{"error":"fixture request limit"})
        body=json.loads(self.rfile.read(size))
        if body.get("model")!="synthetic-contract-fixture":return self.send_json(400,{"error":"Not a real model endpoint"})
        with lock:
            calls+=1; current=calls
        if current==1:return self.send_json(429,{"error":"Intentional transient failure for retry verification"})
        blocks=json.loads(body["messages"][1]["content"])["untrusted_document_blocks"]
        candidates=[]
        for b in blocks:
            if "响应时限:" in unicodedata.normalize("NFKC",b["text"]):
                title,text="响应时限候选（合成验收）","接报后应在2小时内响应。"
            elif "培训服务:" in unicodedata.normalize("NFKC",b["text"]):
                title,text="培训次数候选（合成验收）","应提供不少于2次操作培训。"
            else:continue
            candidates.append({"title":title,"text":text,"category":"TECHNICAL","priority":"GENERAL",
                "rationale":"合成HTTP接口验收结果，无真实模型推理，不用于评价抽取效果。","block_ids":[b["block_id"]]})
        self.send_json(200,{"choices":[{"finish_reason":"stop","message":{"content":json.dumps({"candidates":candidates},ensure_ascii=False)}}],
            "usage":{"prompt_tokens":100,"completion_tokens":80,"total_tokens":180}})


if __name__=="__main__":
    ThreadingHTTPServer(("0.0.0.0",19091),Handler).serve_forever()
