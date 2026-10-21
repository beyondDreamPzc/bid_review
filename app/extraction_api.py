"""模型候选与人工采纳接口；永不直接确认或发布要求。"""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import business as b, business_schemas as s, models as m
from app.api_docs import error_responses
from app.config import get_settings
from app.dependencies import CurrentUser, DB, ProjectID, WriteKey
from app.extraction_model import ExtractionError, config_snapshot
from app import extraction_service as e

router=APIRouter(prefix="/api/v1",tags=["13 AI要求候选"])
RunID=Annotated[str,Path(description="抽取任务 ID，从创建任务或任务列表取得，不是通用 job_id。")]
CandidateID=Annotated[str,Path(description="待人工核对的候选要求 ID。")]
ERRORS=error_responses(401,403,404,409,422,503)


class ConfigResponse(BaseModel):
    configured: bool=Field(description="服务已启用且地址、模型、密钥齐备；不代表云模型已实际调用验证。")
    provider_origin: str|None=Field(description="处理目的地的协议和主机，不包含密钥或查询参数。")
    model: str|None=Field(description="运维配置的模型名称；不在网页选择任意外部地址。")
    config_fingerprint: str|None=Field(description="非敏感配置摘要，创建任务时回传，避免界面确认后模型目的地被改变。")
    reason: str=Field(description="中文配置说明，无密钥明文。")


class RunInput(BaseModel):
    artifact_id: str=Field(description="最新招标或更正 PDF 修订的解析产物 ID。")
    pages: list[int]=Field(min_length=1,max_length=10,description="明确选择1至10个实际页序；每页须有人标记 TEXT_USABLE，不能重复。单次原文最多48000字符、8批。")
    expected_config_fingerprint: str=Field(min_length=64,max_length=64,description="配置接口返回的当前摘要；配置变化须重新确认。")
    acknowledge_external_processing: Literal[True]=Field(description="明确同意将所选页面的提取原文发送给页面展示的已配置模型服务；必须为true。")


class RunResponse(BaseModel):
    id: str=Field(description="抽取业务任务 ID。")
    artifact_id: str=Field(description="固定输入解析产物 ID。")
    job_id: str=Field(description="MySQL/outbox 对应的执行任务 ID。")
    status: str=Field(description="QUEUED/RUNNING/RETRY_WAIT/SUCCEEDED/FAILED/CANCELLED；成功只表示候选生成完成。")
    attempt: int=Field(description="Worker 领取次数，手工重试后重新计数。")
    pages: list[int]=Field(description="所选实际页序。")
    batch_count: int=Field(description="按不截断原文块的8000字符预算分批数，最多8。")
    completed_batch_count: int=Field(description="已校验并保存的批次数；重试保留完成批次。")
    model: str=Field(description="创建时冻结的模型名称。")
    provider_origin: str=Field(description="创建时冻结的模型服务目的地。")
    prompt_profile: str=Field(description="冻结的提示词版本。")
    input_hash: str=Field(description="输入产物、页级质量意见、模型和提示词配置的摘要。")
    freshness: str=Field(description="CURRENT或STALE；文件上传新修订或选页质量意见变化时过期，不能直接采纳旧候选。")
    error_code: str|None=Field(description="最近错误代码，无失败时为空。")
    error_detail: str|None=Field(description="不含密钥、原始失败响应和文档正文的说明。")
    usage: dict[str,int]=Field(description="已完成批次的模型用量汇总；服务未返回时为空，不据此估算费用。")
    created_at: datetime=Field(description="UTC 创建时间。")
    completed_at: datetime|None=Field(description="完成、取消或显式失败时的UTC时间；租约耗尽等情况可能为空。")


class CandidateResponse(BaseModel):
    id: str=Field(description="候选要求 ID。")
    run_id: str=Field(description="来源抽取任务 ID。")
    proposed: dict=Field(description="不可变模型原建议，含标题、正文、类别、重要性、理由和引用块 ID。它不是已确认的招标要求。")
    sources: list[s.EvidenceSnapshot]=Field(description="服务端从允许的输入块回查的出处，不采用模型自造引文。")
    status: str=Field(description="PENDING待处理、IMPORTED已采纳为草稿、REJECTED人工忽略。")
    version: int=Field(description="当前候选处理版本，决定时回传 expected_version。")
    requirement_id: str|None=Field(description="采纳后关联的逻辑要求 ID，尚未采纳为空。")
    review: dict|None=Field(description="一次不可变人工处理凭据，包含动作、说明、实际人及采纳时编辑后的内容。")
    freshness: str=Field(description="输入CURRENT或STALE；旧候选可忽略，但不能直接采纳。")
    created_at: datetime=Field(description="UTC 创建时间。")


class EditedRequirement(s.NonBlank):
    title: str=Field(min_length=1,max_length=200,description="人工核对或修改后的标题。")
    text: str=Field(min_length=1,max_length=8000,description="人工核对或修改后的完整要求，保留范围和例外。")
    category: Literal["TECHNICAL","QUALIFICATION","DELIVERY","FORMAT","OTHER"]=Field(description="人工选择的要求类别。")
    priority: Literal["MANDATORY","SCORING","GENERAL"]=Field(description="人工选择的重要性，不直接信任模型推断。")


class CandidateDecision(s.NonBlank):
    expected_version: int=Field(ge=1,description="候选当前版本，防止另一人已采纳后重复创建要求。")
    action: Literal["IMPORT","REJECT"]=Field(description="IMPORT采纳为待确认草稿；REJECT忽略。均须OWNER/EDITOR。")
    note: str=Field(min_length=1,max_length=4000,description="人工处理意见，说明核对或忽略原因。")
    requirement: EditedRequirement|None=Field(default=None,description="IMPORT必填的人工核对后内容；引用固定为候选原出处，导入后可在要求修订界面继续补充来源。")


class ActionInput(BaseModel):
    expected_attempt: int=Field(ge=0,description="所见任务 attempt，状态变化须刷新；取消可作用于当前运行代次。")


def description(scene,following):
    return (f"**业务场景**：{scene} **下一步**：{following} "
        "业务接口按项目成员隔离，找不到或无权限统一404；写入使用幂等键与项目锁，Cookie写入要求同源Origin。模型不自动发布基线或确认满足，来源仍须人工核对。")


def get_run(db,pid,rid):
    row=db.get(m.ExtractionRun,rid)
    if not row or row.project_id!=pid: raise HTTPException(404,"Extraction run not found")
    return row


@router.get("/extraction/config",operation_id="get_extraction_config",summary="查看模型抽取是否配置及原文处理目的地",
    response_model=ConfigResponse,responses=error_responses(401),
    description=description("开始抽取前，使用人确认已配置服务、模型及原文发送目的地。只返回非敏感状态；配置齐备不代表模型效果已验证。","管理员通过本地环境配置，使用人再明确选择可发送页面；无配置时保留人工整理路径。"))
def model_config(user:CurrentUser):
    return e.public_config(get_settings())


@router.post("/projects/{project_id}/extraction-runs",status_code=202,operation_id="create_extraction_run",summary="从已核对的招标页面发起要求候选抽取",
    response_model=RunResponse,responses=ERRORS,
    description=description("OWNER/EDITOR选择最新招标/更正产物及最多10个已标记文字可用的页面，并明确同意发送到已配置服务。冻结输入、质量意见及模型配置，登记任务与outbox，不在请求内调用模型。超量明确拒绝而非截断。","查询任务进度；全部批次通过结构和引用检查后，才发布待人工处理的候选。"))
def create(project_id:ProjectID,body:RunInput,db:DB,user:CurrentUser,key:WriteKey):
    if any(page<1 for page in body.pages): raise HTTPException(422,"页码从1开始。")
    return b.mutate(db,user,project_id,key,body,"CREATE_EXTRACTION_RUN",b.EDIT,
        lambda d,p,u,v:e.create_run(d,p,u,v,get_settings()))


@router.get("/projects/{project_id}/extraction-runs",operation_id="list_extraction_runs",summary="查看项目最近的候选抽取任务",
    response_model=list[RunResponse],responses=error_responses(401,404,422),
    description=description("任意成员查看任务状态、完成批次、固定模型和失败原因。按新到旧分页返回，不返回模型密钥、完整输入请求或原始失败响应。已成功但输入变化的任务仍保留并显示过期。","打开具体任务查看进度或候选；失败后由编写成员决定是否重试。"))
def runs(project_id:ProjectID,db:DB,user:CurrentUser,
    offset:int=Query(default=0,ge=0,description="跳过任务数。"),limit:int=Query(default=30,ge=1,le=100,description="最多返回任务数，最大100。")):
    b.access(db,project_id,user)
    return [e.run_dto(db,r) for r in db.scalars(select(m.ExtractionRun).where(m.ExtractionRun.project_id==project_id)
        .order_by(m.ExtractionRun.created_at.desc(),m.ExtractionRun.id.desc()).offset(offset).limit(limit))]


@router.get("/projects/{project_id}/extraction-runs/{run_id}",operation_id="get_extraction_run",summary="查询单个要求抽取任务的状态与批次进度",
    response_model=RunResponse,responses=error_responses(401,404,422),
    description=description("任意项目成员在后台任务运行时查询完成批次和错误。进度统计已成功校验并写入MySQL的批次，不用时间推算百分比。输入版本变化会显示过期。","SUCCEEDED后查询该任务候选；FAILED查看原因，CANCELLED不会再发布候选。"))
def run(project_id:ProjectID,run_id:RunID,db:DB,user:CurrentUser):
    b.access(db,project_id,user)
    return e.run_dto(db,get_run(db,project_id,run_id))


def job_action(db,project,user,body,rid,cancel):
    run=get_run(db,project.id,rid)
    job=db.scalar(select(m.Job).where(m.Job.id==run.job_id).with_for_update())
    if job.attempt!=body.expected_attempt: raise HTTPException(409,"Task attempt changed; reload")
    if cancel:
        if job.status not in e.ACTIVE: raise HTTPException(409,"Only an active task can be cancelled")
        job.status="CANCELLED"; job.lease_token+=1; job.lease_until=None; run.completed_at=m.utcnow()
    else:
        if job.status!="FAILED": raise HTTPException(409,"Only a failed task can be retried")
        try:
            if config_snapshot(get_settings())!=run.model_config_snapshot:
                raise HTTPException(409,"模型配置已变化，请新建抽取任务。")
            e.verify_input(db,run,require_creator=True)
        except (ExtractionError,ValueError) as error:
            raise HTTPException(409,str(error)) from None
        job.status="QUEUED";job.attempt=0;job.lease_token+=1;job.lease_until=None
        job.error_code=None;job.error_detail=None;job.next_attempt_at=m.utcnow();job.last_dispatched_at=None
        event=db.scalar(select(m.OutboxEvent).where(m.OutboxEvent.job_id==job.id).with_for_update())
        event.status="PENDING";event.claim_token=None;event.lease_until=None;run.completed_at=None
    db.flush()
    return e.run_dto(db,run)


@router.post("/projects/{project_id}/extraction-runs/{run_id}/retry",operation_id="retry_extraction_run",summary="明确重试失败的抽取任务并保留完成批次",
    response_model=RunResponse,responses=ERRORS,
    description=description("OWNER/EDITOR修复临时服务或密钥问题后明确重试。只允许FAILED且输入、配置仍一致；已完成批次保留，未完成批次可能再次调用并计费，超时重发不能保证云端只执行一次。","查看任务进度；文件、质量意见或模型配置变化应新建任务而非复用旧结果。"))
def retry(project_id:ProjectID,run_id:RunID,body:ActionInput,db:DB,user:CurrentUser,key:WriteKey):
    return b.mutate(db,user,project_id,key,body,f"RETRY_EXTRACTION:{run_id}",b.EDIT,
        lambda d,p,u,v:job_action(d,p,u,v,run_id,False))


@router.post("/projects/{project_id}/extraction-runs/{run_id}/cancel",operation_id="cancel_extraction_run",summary="取消活动抽取任务并阻止后续候选发布",
    response_model=RunResponse,responses=ERRORS,
    description=description("OWNER/EDITOR不再需要当前抽取时取消。递增租约令牌以拒绝旧Worker写入，停止后续批次；已发出的云端请求可能仍执行和计费，不能承诺远程撤销。保留任务事实而不删除历史。","需要重新处理时创建新任务；取消任务不会改变正式要求、材料或审查结论。"))
def cancel(project_id:ProjectID,run_id:RunID,body:ActionInput,db:DB,user:CurrentUser,key:WriteKey):
    return b.mutate(db,user,project_id,key,body,f"CANCEL_EXTRACTION:{run_id}",b.EDIT,
        lambda d,p,u,v:job_action(d,p,u,v,run_id,True))


@router.get("/projects/{project_id}/requirement-candidates",operation_id="list_requirement_candidates",summary="分页阅读模型候选、出处与人工处理状态",
    response_model=list[CandidateResponse],responses=error_responses(401,404,422),
    description=description("任意成员查看结构与引用已通过服务端校验的候选建议。可按任务过滤，按创建时间和ID分页，不将模型理由当作事实，不把待审候选直接计入基线或覆盖率。","编写人逐项回看原文，修改后采纳为草稿，或说明原因忽略；旧输入候选禁止直接采纳。"))
def candidates(project_id:ProjectID,db:DB,user:CurrentUser,
    run_id:str|None=Query(default=None,description="可选来源抽取任务ID。"),
    offset:int=Query(default=0,ge=0,description="跳过的候选条数。"),limit:int=Query(default=50,ge=1,le=100,description="每页最多100条。")):
    b.access(db,project_id,user)
    statement=select(m.RequirementCandidate).where(m.RequirementCandidate.project_id==project_id)
    if run_id:
        get_run(db,project_id,run_id)
        statement=statement.where(m.RequirementCandidate.run_id==run_id)
    return [e.candidate_dto(db,r) for r in db.scalars(statement.order_by(m.RequirementCandidate.created_at,m.RequirementCandidate.id).offset(offset).limit(limit))]


@router.post("/projects/{project_id}/requirement-candidates/{candidate_id}/decisions",operation_id="decide_requirement_candidate",
    summary="人工修改并采纳候选为要求草稿，或说明原因忽略",response_model=CandidateResponse,responses=ERRORS,
    description=description("OWNER/EDITOR逐项回看原文后决定采纳或忽略，使用候选版本和幂等键防重复。原模型建议不覆盖，处理凭据保存编辑后内容、说明和实际人。采纳只创建DRAFT，来源由服务端固定回查；完全相同正文与来源的已有要求会拒绝重复导入。","到整理要求页面核对草稿、补充来源并确认，然后由原有接口显式发布基线。模型和采纳接口都不自动确认。"))
def decide(project_id:ProjectID,candidate_id:CandidateID,body:CandidateDecision,db:DB,user:CurrentUser,key:WriteKey):
    def apply(db,project,actor,value):
        row=db.get(m.RequirementCandidate,candidate_id)
        if not row or row.project_id!=project.id: raise HTTPException(404,"Candidate not found")
        if row.status!="PENDING" or row.version!=value.expected_version: raise HTTPException(409,"Candidate already changed; reload")
        edited=None
        if value.action=="IMPORT":
            if value.requirement is None: raise HTTPException(422,"采纳必须填写人工核对后的要求内容。")
            run=get_run(db,project.id,row.run_id)
            if db.get(m.Job,run.job_id).status!="SUCCEEDED": raise HTTPException(409,"Extraction is not complete")
            try: e.verify_input(db,run)
            except ExtractionError as error: raise HTTPException(409,str(error)) from None
            for existing in b.latest_requirements(db,project.id):
                if e.candidate_fingerprint({"text":existing.text},existing.sources)==e.candidate_fingerprint(value.requirement.model_dump(),row.sources):
                    raise HTTPException(409,"已有相同正文和出处的要求，请核对后忽略重复候选。")
            edited=b.create_requirement(db,project,actor,s.RequirementInput(**value.requirement.model_dump(),
                sources=[s.SourceReference(artifact_id=r["artifact_id"],block_id=r["block_id"]) for r in row.sources]))
            row.requirement_id=edited["requirement_id"]
        row.status="IMPORTED" if value.action=="IMPORT" else "REJECTED"
        row.version+=1
        row.review=jsonable_encoder({"action":value.action,"note":value.note,"decided_by":actor.id,
            "created_at":m.utcnow().isoformat(),"requirement":edited})
        db.flush()
        return e.candidate_dto(db,row)
    return b.mutate(db,user,project_id,key,body,f"DECIDE_CANDIDATE:{candidate_id}",b.EDIT,apply)
