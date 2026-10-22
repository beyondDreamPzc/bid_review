from typing import Annotated as PathAnnotated
from fastapi import Path as APIPath
from typing import Literal
from urllib.parse import urlsplit
from fastapi import APIRouter,Query
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from app import assistant_service as a,business as b,business_schemas as bs,models as m
from app.config import get_settings
from app.dependencies import CurrentUser,DB,ProjectID,WriteKey
from app.extraction_model import ExtractionError,config_snapshot
from app.api_docs import error_responses

router=APIRouter(prefix="/api/v1",tags=["18 证据问答与辅助检查"])
errors=error_responses(401,403,404,409,422,503)


class AssistantInput(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    kind:Literal["QUESTION","REQUIREMENT_CHECK"]=Field(description="QUESTION证据问答；REQUIREMENT_CHECK针对当前要求生成审查建议，后者仅负责人/审查人。")
    question:str=Field(default="",max_length=400,description="证据问答的问题；逐项检查时由服务器读取完整要求，不能伪造要求正文。")
    requirement_revision_id:str|None=Field(default=None,description="逐项检查时本轮基线里的要求修订ID。")
    expected_epoch:int=Field(ge=0,description="页面当前审查输入版本。")
    expected_material_set_id:str=Field(description="当前正式材料集ID。")
    consent:Literal[True]=Field(description="明确允许把本次问题/要求及选定响应片段发送到已显示的模型服务。")
    config_fingerprint:str=Field(description="GET助手配置返回的配置摘要，目的地/模型变化时需重新确认。")


class RunCreated(BaseModel):
    id:str=Field(description="助手任务ID，不是问题或人工审核结论。")
    job_id:str=Field(description="后台执行任务ID，202后继续轮询。")


class AssistantResponse(BaseModel):
    id:str=Field(description="助手记录ID。")
    job_id:str=Field(description="后台任务ID。")
    status:str=Field(description="任务状态；SUCCEEDED只表示建议生成成功。")
    kind:str=Field(description="QUESTION或REQUIREMENT_CHECK。")
    question:str=Field(description="冻结的问题或完整要求。")
    requirement_revision_id:str|None=Field(description="逐项检查绑定的要求修订。")
    sources:list[dict]=Field(description="冻结的服务器检索证据，S序号映射到PDF版本、页码和原文。")
    result:dict=Field(description="output.verdict/answer/citations、usage及配置profile；不是最终决定。")
    freshness:str=Field(description="CURRENT或STALE；输入/问题代次变化后不能采纳旧建议。")
    error_detail:str|None=Field(description="安全的失败提示，不返回模型原始错误体。")


class ConfigResponse(BaseModel):
    configured:bool=Field(description="是否具备完整模型配置，不代表实际联网验证已通过。")
    model:str|None=Field(description="配置的模型名。")
    provider_origin:str|None=Field(description="将接收本次内容的模型服务来源。")
    config_fingerprint:str|None=Field(description="非密钥配置摘要，发起任务时回传。")
    reason:str|None=Field(description="未配置原因；无密钥内容。")


class ControlInput(BaseModel):
    action:Literal["CANCEL","RETRY"]=Field(description="取消活动任务或重试失败任务；不能撤销已发送的外部网络请求。")
    expected_status:str=Field(description="当前看到的任务状态，变化409。")


@router.get("/assistant/config",response_model=ConfigResponse,operation_id="get_assistant_config",
    summary="确认辅助检查的模型与内容处理目的地",responses=error_responses(401),
    description="已有账号可读，不返回密钥。发起问答/逐项检查前，必须显示模型服务来源并由操作者明确确认允许发送本次片段。配置完整不等于模型兼容或语义效果已验证。业务场景：进入辅助检查前说明哪些内容会发往哪个服务。网页使用配置指纹和本次勾选许可发起任务，配置变化要求重新确认；查询不探测云模型，不产生推理费用。")
def config(user:CurrentUser):
    try:
        snapshot=config_snapshot(get_settings());url=urlsplit(snapshot["base_url"])
        return {"configured":True,"model":snapshot["model"],"provider_origin":f"{url.scheme}://{url.netloc}",
            "config_fingerprint":a.fingerprint(snapshot),"reason":None}
    except ExtractionError as error:
        return {"configured":False,"model":None,"provider_origin":None,"config_fingerprint":None,"reason":str(error)}


def dto(db,run,user):
    job=db.get(m.Job,run.job_id);freshness="CURRENT"
    try:a.verify(db,run,user)
    except Exception:freshness="STALE"
    return {"id":run.id,"job_id":job.id,"status":job.status,"kind":run.kind,"question":run.question,
        "requirement_revision_id":run.requirement_revision_id,"sources":run.sources,"result":run.result,
        "freshness":freshness,"error_detail":job.error_detail}


@router.post("/projects/{project_id}/assistant-runs",status_code=202,response_model=RunCreated,
    operation_id="create_assistant_run",summary="异步生成有引用的证据问答或逐项检查建议",responses=errors,
    description="先建好本轮正式材料索引并明确模型发送许可。使用检索、结构化模型输出、引用白名单、输入复核与租约发布的有界步骤；最多3个活动任务。仅把建议写入助手记录，不生成最终满足结论。人工检查出处后，疑似问题可明确采纳为普通整改问题。")
def create(project_id:ProjectID,body:AssistantInput,db:DB,user:CurrentUser,key:WriteKey):
    try:return b.mutate(db,user,project_id,key,body,"CREATE_ASSISTANT_RUN",None,
        lambda d,p,u,v:a.enqueue(d,p,u,v,get_settings()))
    except ExtractionError as error:b.fail(503,str(error))


@router.get("/projects/{project_id}/assistant-runs",response_model=list[AssistantResponse],
    operation_id="list_assistant_runs",summary="查看辅助建议及输入过期状态",responses=error_responses(401,404),
    description="项目成员查看最近记录，区分任务执行成功、业务输入有效与人工采纳。证据和建议历史保留；材料或要求变化后旧结果标为STALE。业务场景：追踪排队任务并查看已生成分析、证据与错误提示。结果中的来源链接指向不可变PDF，模型分析不会覆盖人工作业记录；STALE记录保留供追溯，应使用当前输入重新检查。")
def listing(project_id:ProjectID,db:DB,user:CurrentUser,limit:int=Query(default=30,ge=1,le=100,description="最近记录条数。")):
    b.access(db,project_id,user)
    return [dto(db,row,user) for row in db.scalars(select(m.AssistantRun).where(m.AssistantRun.project_id==project_id)
        .order_by(m.AssistantRun.created_at.desc()).limit(limit))]


@router.post("/projects/{project_id}/assistant-runs/{run_id}/control",response_model=AssistantResponse,
    operation_id="control_assistant_run",summary="取消或明确重试辅助检查",responses=errors,
    description="负责人或任务发起人可取消活动任务，立即递增租约隔离迟到结果；无法撤回已经发送的云请求。失败重试须输入仍有效且模型配置相同，继续使用冻结证据，不重新编造上下文。完成记录不能取消。请求须携带当前expected_status和幂等键，避免并发取消覆盖已完成结果。取消后旧Worker不得发布结果，重试不代表已通过模型或人工检查。")
def control(project_id:ProjectID,run_id:PathAnnotated[str,APIPath(description="辅助建议运行记录ID，不是后台job_id。")],body:ControlInput,db:DB,user:CurrentUser,key:WriteKey):
    def apply(db,project,actor,value):
        run=db.get(m.AssistantRun,run_id)
        if not run or run.project_id!=project.id:b.fail(404,"助手记录不存在。")
        if run.created_by!=actor.id and db.get(m.ProjectMember,(project.id,actor.id)).role!="OWNER":b.fail(403,"只有发起人或负责人可以控制任务。")
        job=db.scalar(select(m.Job).where(m.Job.id==run.job_id).with_for_update())
        if job.status!=value.expected_status:b.fail(409,"任务状态已变化。")
        if value.action=="CANCEL":
            if job.status not in {"QUEUED","RUNNING","RETRY_WAIT"}:b.fail(409,"只可取消活动任务。")
            job.status="CANCELLED";job.lease_token+=1;job.lease_until=None
        else:
            if job.status!="FAILED":b.fail(409,"只可重试失败任务。")
            a.verify(db,run,actor)
            if config_snapshot(get_settings())!=run.model_profile:b.fail(409,"模型配置已变，请新建任务。")
            job.status="QUEUED";job.attempt=0;job.lease_token+=1;job.lease_until=None
            job.next_attempt_at=m.utcnow();job.last_dispatched_at=None;job.error_code=job.error_detail=None
            event=db.scalar(select(m.OutboxEvent).where(m.OutboxEvent.job_id==job.id))
            if event:event.status="PENDING";event.claim_token=None;event.lease_until=None
            else:db.add(m.OutboxEvent(job_id=job.id))
        return dto(db,run,actor)
    try:return b.mutate(db,user,project_id,key,body,f"CONTROL_ASSISTANT:{run_id}",None,apply)
    except ExtractionError as error:b.fail(503,str(error))


@router.post("/projects/{project_id}/assistant-runs/{run_id}/adopt",response_model=bs.IssueResponse,
    operation_id="adopt_assistant_issue",summary="人工编辑并采纳疑似问题为整改任务",responses=errors,
    description="仅OWNER/REVIEWER。只接受当前逐项检查的疑似问题/证据不足建议，必须人工选择问题类型、完整描述及负责人。引用只能来自该建议实际使用的响应证据；无法自动确认响应缺失。采纳使用既有问题/任务规则与幂等锁，不跳过独立复核或最终人工判断。")
def adopt(project_id:ProjectID,run_id:PathAnnotated[str,APIPath(description="辅助建议运行记录ID，不是后台job_id。")],body:bs.IssueInput,db:DB,user:CurrentUser,key:WriteKey):
    def apply(db,project,actor,value):
        run=db.get(m.AssistantRun,run_id)
        if not run or run.project_id!=project.id:b.fail(404,"助手记录不存在。")
        a.verify(db,run,actor)
        if run.kind!="REQUIREMENT_CHECK" or db.get(m.Job,run.job_id).status!="SUCCEEDED":b.fail(409,"不是可采纳的逐项检查。")
        if run.result.get("adopted_issue_id") or run.result["output"]["verdict"]=="SUPPORTED":b.fail(409,"该建议已采纳或不属于疑似问题。")
        if value.requirement_revision_id!=run.requirement_revision_id:b.fail(422,"不能把建议转给其他要求。")
        allowed={(s["source"]["artifact_id"],s["source"]["block_id"]) for s in run.sources if s["id"] in run.result["output"]["citations"]}
        if any((ref.artifact_id,ref.block_id) not in allowed for ref in value.evidence):b.fail(422,"证据不在该建议的引用范围内。")
        issue=b.create_issue(db,project,actor,value)
        run.result={**run.result,"adopted_issue_id":issue["id"]};return issue
    return b.mutate(db,user,project_id,key,body,f"ADOPT_ASSISTANT:{run_id}",b.REVIEW,apply)
