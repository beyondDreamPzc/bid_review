"""同一不可变 PDF 可以新增解析配置，旧产物及其引用始终保留。"""
from typing import Annotated

from fastapi import APIRouter,HTTPException,Path
from pydantic import BaseModel,Field
from sqlalchemy import select

from app import business as b,models as m
from app.api_docs import error_responses
from app.config import get_settings
from app.dependencies import CurrentUser,DB,WriteKey
from app.mineru_parser import PROFILES
from app.parsers import PROFILE,PARSE_JOB_KINDS

router=APIRouter(prefix="/api/v1",tags=["02 文档与修订"])


class ReparseInput(BaseModel):
    retry_failed: bool=Field(default=False,description="明确重试本配置已失败的解析任务；完成或活动任务直接复用。不是删除重跑。")


class ReparseResponse(BaseModel):
    revision_id: str=Field(description="不变的原 PDF 修订 ID；重解析不创建新文件修订。")
    job_id: str=Field(description="该修订及配置对应的后台解析任务 ID。")
    parser_profile: str=Field(description="本次冻结的解析配置；MinerU版本、档位、模式和适配规则分别固定。")
    reused: bool=Field(description="是否复用已有的同配置任务。")


@router.post("/revisions/{revision_id}/parse",status_code=202,operation_id="reparse_revision",
    summary="用当前解析配置重新解析原 PDF，保留旧产物与引用",response_model=ReparseResponse,
    responses=error_responses(401,403,404,409,422,503),
    description="**业务场景**：已有PDF曾用旧文字层探针解析，升级MinerU后需要生成新结果，无需重新上传或伪造文件修订。仅OWNER/EDITOR，使用幂等键、项目锁和revision/profile去重；相同配置直接复用任务，明确retry_failed时才重试失败任务。202只表示登记成功，随后查询job_id。网络和模型推理在Worker执行。新产物不继承旧质量意见，不覆盖已有要求出处、正式材料、基线或审查结论；仍须打开原件核对后明确采用。")
def reparse(revision_id:Annotated[str,Path(description="已有不可变PDF修订ID，从文件列表取得。")],
            body:ReparseInput,db:DB,user:CurrentUser,key:WriteKey):
    revision=db.get(m.DocumentRevision,revision_id)
    document=db.get(m.Document,revision.document_id) if revision else None
    if not document:raise HTTPException(404,"Revision not found")
    def apply(db,project,actor,value):
        profile=get_settings().parser_profile
        if profile!=PROFILE and profile not in PROFILES:raise HTTPException(503,"解析配置不受支持，请检查API与Worker版本。")
        dedup=f"parse:{revision_id}:{profile}"
        job=db.scalar(select(m.Job).where(m.Job.dedup_key==dedup).with_for_update())
        reused=job is not None
        if job is None or job.status=="FAILED" and value.retry_failed:
            statement=select(m.Job).where(m.Job.revision_id==revision_id,m.Job.kind.in_(PARSE_JOB_KINDS),
                m.Job.status.in_(["QUEUED","RUNNING","RETRY_WAIT"]))
            if job is not None:statement=statement.where(m.Job.id!=job.id)
            if db.scalar(statement):raise HTTPException(409,"此文件还有解析任务未结束，请等待后再切换或重试解析配置。")
        if job and job.status=="FAILED" and value.retry_failed:
            job.status="QUEUED";job.attempt=0;job.lease_token+=1;job.lease_until=None
            job.error_code=None;job.error_detail=None;job.next_attempt_at=m.utcnow();job.last_dispatched_at=None
            event=db.scalar(select(m.OutboxEvent).where(m.OutboxEvent.job_id==job.id).with_for_update())
            if event:event.status="PENDING";event.claim_token=None;event.lease_until=None
            else:db.add(m.OutboxEvent(job_id=job.id))
        elif job is None:
            job=m.Job(project_id=project.id,revision_id=revision_id,kind="PDF_TEXT_PROBE" if profile==PROFILE else "PDF_PARSE",
                      parser_profile=profile,dedup_key=dedup)
            db.add(job);db.flush();db.add(m.OutboxEvent(job_id=job.id))
        return {"revision_id":revision_id,"job_id":job.id,"parser_profile":profile,"reused":reused}
    return b.mutate(db,user,document.project_id,key,body,f"REPARSE_REVISION:{revision_id}",b.EDIT,apply)
