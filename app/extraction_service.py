"""抽取输入冻结、版本检查与候选 DTO，复用既有项目事务规则。"""
import json
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import func, select

from app import business as b, business_schemas as s, models as m
from app.extraction_model import PROMPT_PROFILE, ExtractionError, config_snapshot
from app.quality_api import payload
from app.storage import sha256

KIND = "REQUIREMENT_EXTRACTION"
ACTIVE = {"QUEUED", "RUNNING", "RETRY_WAIT"}


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode())


def origin(config):
    parts=urlsplit(config["base_url"])
    return f"{parts.scheme}://{parts.netloc}"


def public_config(settings):
    try:
        config=config_snapshot(settings)
        return {"configured":True,"provider_origin":origin(config),"model":config["model"],
                "config_fingerprint":digest(config),"reason":"已配置，提交前请确认所选页可发送到此服务。"}
    except (ExtractionError,ValueError):
        return {"configured":False,"provider_origin":None,"model":None,"config_fingerprint":None,
                "reason":"请在本地环境配置并启用模型服务；没有模型时不会生成模拟候选。"}


def latest_review(db, artifact_id, page):
    return db.scalar(select(m.PageQualityReview).where(m.PageQualityReview.artifact_id==artifact_id,
        m.PageQualityReview.page==page).order_by(m.PageQualityReview.version.desc()).limit(1))


def is_current(db, run, require_creator=False):
    artifact, revision, document=b.artifact_parts(db,run.project_id,run.artifact_id)
    newest=db.scalar(select(func.max(m.DocumentRevision.revision_no)).where(m.DocumentRevision.document_id==document.id))
    if revision.revision_no!=newest:
        return False
    if require_creator:
        member=db.get(m.ProjectMember,(run.project_id,run.created_by))
        if not member or member.role not in b.EDIT:
            return False
    for frozen in run.page_reviews:
        review=latest_review(db,artifact.id,frozen["page"])
        if not review or review.id!=frozen["review_id"] or review.decision!="TEXT_USABLE":
            return False
    return True


def verify_input(db, run, require_creator=False):
    if not is_current(db,run,require_creator):
        raise ExtractionError("EXTRACTION_INPUT_CHANGED","文件版本、页级质量意见或发起人权限已变化，请重新核对并新建抽取任务。")
    artifact,_,_=b.artifact_parts(db,run.project_id,run.artifact_id)
    frozen=payload(artifact)
    blocks={block["block_id"]:block for block in frozen["blocks"]}
    for batch in run.batches:
        for ref in batch["blocks"]:
            actual=blocks.get(ref["block_id"])
            stored=db.get(m.DocumentBlock,(run.artifact_id,ref["block_id"]))
            if (not actual or not stored or actual["text_hash"]!=ref["text_hash"]
                    or sha256(stored.text.encode())!=ref["text_hash"] or stored.page!=ref["page"]):
                raise ExtractionError("EXTRACTION_INPUT_CHANGED","冻结原文的完整性校验失败，已停止模型处理。")


def create_run(db, project, user, body, settings):
    try:
        config=config_snapshot(settings)
    except (ExtractionError,ValueError):
        raise HTTPException(503,"模型服务尚未完整配置；请先配置并重启 API 与抽取 Worker。") from None
    if body.expected_config_fingerprint!=digest(config):
        raise HTTPException(409,"模型配置已变化，请重新确认处理目的地。")
    if len(body.pages)!=len(set(body.pages)):
        raise HTTPException(422,"页码不能重复。")
    artifact,revision,document=b.artifact_parts(db,project.id,body.artifact_id)
    if document.kind not in {"TENDER","AMENDMENT"}:
        raise HTTPException(422,"只能从招标或更正文件抽取要求。")
    newest=db.scalar(select(func.max(m.DocumentRevision.revision_no)).where(m.DocumentRevision.document_id==document.id))
    if revision.revision_no!=newest:
        raise HTTPException(409,"该文件已有新版，请核对最新修订。")
    reviews=[]
    for page in sorted(body.pages):
        if page>artifact.page_count:
            raise HTTPException(422,"所选页码超出文件范围。")
        review=latest_review(db,artifact.id,page)
        if not review or review.decision!="TEXT_USABLE":
            raise HTTPException(409,f"第 {page} 页尚未人工确认文字可用，请先完成质量核对。")
        reviews.append({"page":page,"review_id":review.id,"version":review.version})
    frozen=payload(artifact)
    blocks=[v for v in frozen["blocks"] if v["page"] in body.pages]
    if not blocks or any(not any(v["page"]==page for v in blocks) for page in body.pages):
        raise HTTPException(422,"所选页面没有可抽取文字。")
    if sum(len(v["text"]) for v in blocks)>48000 or any(len(v["text"])>8000 for v in blocks):
        raise HTTPException(422,"所选原文超出本次处理上限，请缩小页范围；不会静默截断。")
    refs=b.sources(db,project,[s.SourceReference(artifact_id=artifact.id,block_id=v["block_id"]) for v in blocks],tender=True)
    by_id={v["block_id"]:v for v in blocks}
    if any(r["text_hash"]!=by_id[r["block_id"]]["text_hash"] for r in refs):
        raise HTTPException(503,"原文索引与冻结产物不一致，请检查存储。")
    input_hash=digest({"artifact":artifact.sha256,"pages":reviews,"model":config,"prompt":PROMPT_PROFILE})
    active=db.scalars(select(m.ExtractionRun).join(m.Job,m.Job.id==m.ExtractionRun.job_id).where(
        m.ExtractionRun.project_id==project.id,m.Job.status.in_(ACTIVE))).all()
    if any(r.input_hash==input_hash for r in active):
        raise HTTPException(409,"相同文件与页范围已有运行中的抽取任务，请查看任务列表。")
    if len(active)>=3:
        raise HTTPException(409,"本项目已有3个待完成抽取任务，请等待或取消后再创建。")
    batches=[]
    for ref in refs:
        if not batches or sum(len(v["quote"]) for v in batches[-1]["blocks"])+len(ref["quote"])>8000:
            batches.append({"blocks":[],"result":None})
        batches[-1]["blocks"].append(ref)
    if len(batches)>8:
        raise HTTPException(422,"原文需要超过8批处理，请缩小页面范围后分次抽取。")
    run_id=m.uid()
    job=m.Job(project_id=project.id,revision_id=revision.id,kind=KIND,
        dedup_key=f"extract:{run_id}",parser_profile=PROMPT_PROFILE)
    db.add(job); db.flush()
    run=m.ExtractionRun(id=run_id,project_id=project.id,artifact_id=artifact.id,job_id=job.id,
        input_hash=input_hash,page_reviews=reviews,batches=batches,model_config_snapshot=config,
        prompt_profile=PROMPT_PROFILE,created_by=user.id)
    db.add(run); db.add(m.OutboxEvent(job_id=job.id)); db.flush()
    return run_dto(db,run)


def run_dto(db,run):
    job=db.get(m.Job,run.job_id)
    usage={}
    for batch in run.batches:
        for k,v in (batch.get("result") or {}).get("usage",{}).items():
            usage[k]=usage.get(k,0)+v
    return {"id":run.id,"artifact_id":run.artifact_id,"job_id":job.id,"status":job.status,
        "attempt":job.attempt,"pages":[r["page"] for r in run.page_reviews],"batch_count":len(run.batches),
        "completed_batch_count":sum(v.get("result") is not None for v in run.batches),
        "model":run.model_config_snapshot["model"],"provider_origin":origin(run.model_config_snapshot),
        "prompt_profile":run.prompt_profile,"input_hash":run.input_hash,
        "freshness":"CURRENT" if is_current(db,run) else "STALE",
        "error_code":job.error_code,"error_detail":job.error_detail,"usage":usage,
        "created_at":run.created_at,"completed_at":run.completed_at}


def candidate_dto(db,row):
    run=db.get(m.ExtractionRun,row.run_id)
    return {"id":row.id,"run_id":row.run_id,"proposed":row.proposed,"sources":row.sources,
        "status":row.status,"version":row.version,"requirement_id":row.requirement_id,"review":row.review,
        "freshness":"CURRENT" if is_current(db,run) else "STALE","created_at":row.created_at}


def candidate_fingerprint(proposed,sources):
    return digest({"text":"".join(proposed["text"].split()).casefold(),
        "sources":sorted((s["artifact_id"],s["block_id"]) for s in sources)})
