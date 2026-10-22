"""User-run synthetic end-to-end corpus evaluation. Never invent scores when services are absent."""
import argparse
import io
import json
import os
from pathlib import Path
import statistics
import time
import uuid
from xml.sax.saxutils import escape
from zipfile import ZipFile,ZIP_DEFLATED
import httpx
from dotenv import dotenv_values


def docx(paragraphs):
    buffer=io.BytesIO()
    with ZipFile(buffer,"w",ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml",'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        body="".join(f'<w:p><w:r><w:rPr><w:rFonts w:eastAsia="Noto Sans CJK SC"/></w:rPr><w:t>{escape(text)}</w:t></w:r></w:p>' for text in paragraphs)
        archive.writestr("word/document.xml",f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>')
    return buffer.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create-synthetic-projects",action="store_true",required=True,
        help="明确创建三个构造项目，上传DOCX、转换、解析、发布正式材料和构建索引；不调用云模型")
    parser.add_argument("--url",default="http://127.0.0.1:18080")
    parser.add_argument("--output",default="data/evaluation/retrieval-results.json")
    parser.add_argument("--timeout",type=int,default=1800)
    args=parser.parse_args()
    corpus=json.loads((Path(__file__).resolve().parent.parent/"evaluation/retrieval-corpus.json").read_text(encoding="utf-8"))
    key=os.environ.get("BID_BOOTSTRAP_API_KEY") or dotenv_values(".env").get("BID_BOOTSTRAP_API_KEY")
    if not key:raise RuntimeError("Configure the local bootstrap account key before evaluation")
    rows=[]
    with httpx.Client(base_url=args.url,headers={"X-API-Key":key},timeout=120,trust_env=False) as client:
        def get(path):
            response=client.get(path);response.raise_for_status();return response.json()
        def post(path,body):
            response=client.post(path,json=body,headers={"Idempotency-Key":str(uuid.uuid4())})
            response.raise_for_status();return response.json()
        def wait(job_id):
            deadline=time.monotonic()+args.timeout
            while time.monotonic()<deadline:
                job=get("/api/v1/jobs/"+job_id)
                if job["status"]=="SUCCEEDED":return job
                if job["status"] in {"FAILED","CANCELLED"}:raise RuntimeError(job.get("error_detail") or "Job failed")
                time.sleep(2)
            raise TimeoutError("Task not completed; inspect worker status")
        for template in corpus["templates"]:
            project=post("/api/v1/projects",{"name":"构造评测 / "+template["title"]});base="/api/v1/projects/"+project["id"]
            response=client.post(base+"/conversions",data={"title":template["title"],"kind":"RESPONSE"},
                files={"file":("fixture.docx",docx([template["title"],*template["paragraphs"]]),"application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                headers={"Idempotency-Key":str(uuid.uuid4())});response.raise_for_status()
            conversion=response.json();wait(conversion["job_id"])
            conversion=next(c for c in get(base+"/conversions") if c["id"]==conversion["id"])
            deadline=time.monotonic()+args.timeout;artifact=None
            while time.monotonic()<deadline:
                workspace=get(base+"/workbench")
                rev=next(r for d in workspace["documents"] for r in d["revisions"] if r["id"]==conversion["revision_id"])
                if rev["job_status"]=="FAILED":raise RuntimeError("Parser failed")
                if rev["artifact_id"]:artifact=rev["artifact_id"];break
                time.sleep(2)
            if not artifact:raise TimeoutError("PDF parse not completed")
            current=workspace["workspace"]
            material=post(base+"/material-sets",{"expected_epoch":current["review_epoch"],"expected_current_material_set_id":current["current_material_set_id"],"items":[{"artifact_id":artifact,"submission_role":"FORMAL_RESPONSE"}]})
            wait(post(base+"/retrieval/indexes",{"expected_material_set_id":material["id"]})["job_id"])
            for query in template["queries"]:
                start=time.monotonic();result=post(base+"/retrieval/search",{"expected_material_set_id":material["id"],"query":query["query"],"limit":5});latency=time.monotonic()-start
                quotes=[h["quote"] for h in result["results"]]
                found=[any(label in text for text in quotes) for label in query["relevant"]]
                first=next((i for i,text in enumerate(quotes,1) if any(label in text for label in query["relevant"])),None)
                rows.append({"template":template["id"],"project_id":project["id"],"query":query["query"],"profile":result["profile"],"recall_at_5":sum(found)/len(found),"reciprocal_rank":1/first if first else 0,"latency_seconds":latency,"hits":result["results"]})
    report={"scope":corpus["provenance"],"queries":len(rows),"macro_recall_at_5":statistics.mean(r["recall_at_5"] for r in rows),"mrr_at_5":statistics.mean(r["reciprocal_rank"] for r in rows),"mean_latency_seconds":statistics.mean(r["latency_seconds"] for r in rows),"rows":rows}
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="rows"},ensure_ascii=False))


if __name__=="__main__":main()
