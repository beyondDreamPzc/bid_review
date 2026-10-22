from typing import Annotated as PathAnnotated
from fastapi import Path as APIPath
from typing import Literal
from fastapi import APIRouter,Query
from sqlalchemy import func,select
from app import business as b,business_schemas as bs,lifecycle as life,lifecycle_schemas as s,models as m
from app.dependencies import CurrentUser,DB,ProjectID,WriteKey
from app.api_docs import error_responses

router=APIRouter(prefix="/api/v1/projects/{project_id}",tags=["15 协作与变更管理"])
errors=error_responses(401,403,404,409,422)


@router.post("/tasks/{task_id}/assignment",response_model=bs.TaskResponse,operation_id="reassign_task",
    summary="转派整改任务或调整期限",responses=errors,
    description="业务场景：编写人请假、职责调整或整改延期。仅OWNER，携带当前任务version与原因。待复核先完成复核，撤销任务可先转派再恢复；其他状态可转派给本项目OWNER/EDITOR。保留提交和复核历史，不把更换负责人当作整改验收。操作后通知新负责人。")
def assignment(project_id:ProjectID,task_id:PathAnnotated[str,APIPath(description="整改任务ID，从问题或任务列表取得；与项目配套。")],body:s.AssignmentInput,db:DB,user:CurrentUser,key:WriteKey):
    return b.mutate(db,user,project_id,key,body,f"REASSIGN_TASK:{task_id}",{"OWNER"},
        lambda d,p,u,v:life.reassign(d,p,u,v,task_id))


@router.post("/issues/{issue_id}/lifecycle",response_model=bs.IssueResponse,operation_id="withdraw_restore_issue",
    summary="撤销误报问题或恢复整改",responses=errors,
    description="业务场景：人工确认问题为误报或应重新处理。仅OWNER/REVIEWER，带任务version和原因。撤销后不再阻塞当前报告，恢复为TODO；均使该要求旧判断失效，必须重新判断。保留原问题、整改和复核，不自动生成满足结论。")
def issue_lifecycle(project_id:ProjectID,issue_id:PathAnnotated[str,APIPath(description="问题ID，从登记或问题列表取得。")],body:s.WithdrawInput,db:DB,user:CurrentUser,key:WriteKey):
    return b.mutate(db,user,project_id,key,body,f"WITHDRAW_ISSUE:{issue_id}",b.REVIEW,
        lambda d,p,u,v:life.withdraw(d,p,u,v,issue_id))


@router.post("/requirements/{requirement_id}/lifecycle",response_model=s.RetirementResponse,
    operation_id="retire_restore_requirement",summary="退休失效要求或恢复要求",responses=errors,
    description="业务场景：更正取消某要求、重复录入或需恢复误退要求。仅OWNER/REVIEWER，带最新修订号和原因；先撤销该要求的问题。退休不删历史，最新清单排除该要求，旧冻结基线暂保留并提示待发布。重新发布完整基线后才改变本轮范围，恢复也须重新发布。")
def requirement_lifecycle(project_id:ProjectID,requirement_id:PathAnnotated[str,APIPath(description="逻辑要求ID，不是要求修订ID。")],body:s.RetirementInput,db:DB,user:CurrentUser,key:WriteKey):
    return b.mutate(db,user,project_id,key,body,f"RETIRE_REQUIREMENT:{requirement_id}",b.REVIEW,
        lambda d,p,u,v:life.retire(d,p,u,v,requirement_id))


@router.post("/members/{user_id}/remove",response_model=s.RemovedMember,operation_id="remove_project_member",
    summary="移除已交接成员的项目权限",responses=errors,
    description="业务场景：协作者离开项目，负责人完成任务转派后移除访问。仅OWNER，不能移除OWNER；还有未撤销任务时拒绝，已验收任务也应交接以便后续重核。立即影响后续读写权限，历史操作人和署名不删除。成员被移除后仍保留其历史署名、已上传修订和复核记录，新的请求立即按最新成员关系鉴权。")
def remove_member(project_id:ProjectID,user_id:PathAnnotated[str,APIPath(description="拟移除的项目成员用户ID，不是姓名。")],body:s.NoteInput,db:DB,user:CurrentUser,key:WriteKey):
    return b.mutate(db,user,project_id,key,body,f"REMOVE_MEMBER:{user_id}",{"OWNER"},
        lambda d,p,u,v:life.remove_member(d,p,u,v,user_id))


@router.post("/change-impacts",status_code=201,response_model=s.ImpactResponse,
    operation_id="create_change_impact",summary="把更正原文关联到受影响要求",responses=errors,
    description="业务场景：收到更正文件，审查人明确哪些要求可能受影响。仅OWNER/REVIEWER，必须引用本项目AMENDMENT原文并说明原因。只递增关联要求的问题代次；该要求需先处理影响再最终判断，其余要求不因本关联失效。新基线/材料发布仍保留整体失效的保守规则。")
def create_impact(project_id:ProjectID,body:s.ImpactInput,db:DB,user:CurrentUser,key:WriteKey):
    return b.mutate(db,user,project_id,key,body,"CREATE_CHANGE_IMPACT",b.REVIEW,life.create_impact)


@router.get("/change-impacts",response_model=list[s.ImpactResponse],operation_id="list_change_impacts",
    summary="查看更正影响与处理记录",responses=error_responses(401,404),
    description="所有项目成员可查看本项目更正原文、受影响要求和人工处理意见。待处理影响会阻止报告完成，但不会自动更改要求正文或生成整改问题。在审查前打开本清单，逐条查看更正原文与影响说明。修改要求并人工确认后记录REVISED，或写明理由记录NO_CHANGE；本查询不会自动处理任何影响，历史处置也会返回供追溯。")
def impacts(project_id:ProjectID,db:DB,user:CurrentUser):
    b.access(db,project_id,user)
    return [life.impact_dto(row) for row in db.scalars(select(m.ChangeImpact).where(m.ChangeImpact.project_id==project_id)
        .order_by(m.ChangeImpact.created_at.desc()))]


@router.post("/change-impacts/{impact_id}/decision",response_model=s.ImpactResponse,
    operation_id="decide_change_impact",summary="记录更正已修订或人工确认不需修改",responses=errors,
    description="仅OWNER/REVIEWER。REVISED要求最新修订已确认且包含此更正的原文出处；NO_CHANGE须写明人工判断原因。退休通过要求生命周期接口。处理后仍须按当前要求和材料重新判断，不自动沿用旧结论。")
def decide_impact(project_id:ProjectID,impact_id:PathAnnotated[str,APIPath(description="更正影响记录ID，从影响清单取得。")],body:s.ImpactDecisionInput,db:DB,user:CurrentUser,key:WriteKey):
    return b.mutate(db,user,project_id,key,body,f"DECIDE_CHANGE_IMPACT:{impact_id}",b.REVIEW,
        lambda d,p,u,v:life.decide_impact(d,p,u,v,impact_id))


@router.get("/catalog/{resource}",response_model=s.PageResponse,operation_id="search_project_catalog",
    summary="分页筛选项目资料、要求、任务或审计",responses=error_responses(401,404,422),
    description="业务场景：项目记录多时按文字和状态缩小范围，使用offset/limit分页，total为筛选后数量。所有成员可查业务清单，审计仅OWNER/REVIEWER。搜索按字面包含，排序固定；数据变化时刷新分页，不提供跨请求快照。")
def catalog(project_id:ProjectID,resource:PathAnnotated[Literal["requirements","issues","documents","audit"],APIPath(description="requirements要求、issues问题任务、documents资料、audit操作记录。")],db:DB,user:CurrentUser,
            q:str=Query(default="",max_length=100,description="标题/说明中的字面关键词。"),
            status:str=Query(default="",max_length=30,description="要求DRAFT/CONFIRMED/RETIRED；问题TODO等任务状态；文档按kind；审计按action。"),
            offset:int=Query(default=0,ge=0,description="从0开始的偏移。"),
            limit:int=Query(default=20,ge=1,le=100,description="每页条数，最大100。")):
    project,member=b.access(db,project_id,user)
    if resource=="requirements":
        rows=[{**b.req_dto(row),"retired":db.get(m.Requirement,row.requirement_id).retired}
            for row in b.latest_requirements(db,project_id,include_retired=True)]
        rows=[row for row in rows if not status or ("RETIRED" if row["retired"] else row["status"])==status]
    elif resource=="issues":
        rows=[b.issue_dto(db,project,row) for row in db.scalars(select(m.ReviewIssue)
            .where(m.ReviewIssue.project_id==project_id).order_by(m.ReviewIssue.created_at.desc(),m.ReviewIssue.id))]
        rows=[row for row in rows if not status or row["task"]["effective_status"]==status]
    else:
        if resource=="audit" and member.role not in b.REVIEW:b.fail(403,"仅负责人或审查人可以查看审计。")
        model=m.AuditEvent if resource=="audit" else m.Document
        statement=select(model).where(model.project_id==project_id)
        field=model.action if resource=="audit" else model.kind
        search_field=model.action if resource=="audit" else model.title
        if status:statement=statement.where(field==status)
        if q:statement=statement.where(search_field.contains(q,autoescape=True))
        total=db.scalar(select(func.count()).select_from(statement.subquery()))
        records=db.scalars(statement.order_by(model.created_at.desc(),model.id).offset(offset).limit(limit))
        rows=[{column.name:getattr(row,column.name) for column in model.__table__.columns} for row in records]
        return {"items":rows,"total":total,"offset":offset,"limit":limit}
    if q:rows=[row for row in rows if q.casefold() in (row.get("title","")+row.get("text","")+row.get("description","")).casefold()]
    return {"items":rows[offset:offset+limit],"total":len(rows),"offset":offset,"limit":limit}
