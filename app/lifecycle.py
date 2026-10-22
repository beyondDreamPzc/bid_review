"""Explicit human lifecycle actions. Project lock/idempotency are supplied by business.mutate."""
from sqlalchemy import select
from app import business as b,models as m


def audit(db,project,user,action,object_id,details):
    db.add(m.AuditEvent(project_id=project.id,actor_id=user.id,action=action,object_id=object_id,details=details))


def reassign(db,project,user,body,task_id):
    task=b.get_task(db,project.id,task_id)
    if task.version!=body.expected_version:b.fail(409,"任务已变化，请刷新后转派。")
    if task.status=="SUBMITTED":b.fail(409,"待复核任务不能转派，请先完成复核。")
    member=db.get(m.ProjectMember,(project.id,body.assignee_id))
    if not member or member.role not in b.EDIT:b.fail(422,"请选择本项目的负责人或编写人。")
    if db.get(m.User,body.assignee_id).disabled:b.fail(422,"请选择未停用的整改负责人。")
    previous=task.assignee_id
    task.assignee_id=body.assignee_id;task.due_date=body.due_date;task.version+=1
    audit(db,project,user,"TASK_ASSIGNMENT_CHANGED",task.id,
        {"from":previous,"to":task.assignee_id,"note":body.note,"due_date":str(task.due_date or "")})
    db.flush();return b.task_dto(db,project,task)


def withdraw(db,project,user,body,issue_id):
    issue=db.get(m.ReviewIssue,issue_id)
    if not issue or issue.project_id!=project.id:b.fail(404,"问题不存在。")
    task=db.scalar(select(m.WorkItem).where(m.WorkItem.issue_id==issue_id))
    if task.version!=body.expected_version:b.fail(409,"任务已变化，请刷新。")
    if issue.withdrawn==body.withdrawn:b.fail(409,"问题已处于所请求状态。")
    if not body.withdrawn and db.get(m.Requirement,issue.requirement_id).retired:
        b.fail(409,"请先恢复要求，再恢复对应问题。")
    if not body.withdrawn:
        assignee=db.get(m.ProjectMember,(project.id,task.assignee_id))
        if not assignee or assignee.role not in b.EDIT:b.fail(409,"原负责人已不能编辑，请先转派撤销任务后再恢复问题。")
        if db.get(m.User,task.assignee_id).disabled:b.fail(409,"原负责人已停用，请先转派撤销任务。")
    issue.withdrawn=body.withdrawn;task.status="CANCELLED" if body.withdrawn else "TODO";task.version+=1
    db.get(m.Requirement,issue.requirement_id).review_version+=1
    audit(db,project,user,"ISSUE_LIFECYCLE_CHANGED",issue.id,{"withdrawn":body.withdrawn,"note":body.note})
    db.flush();return b.issue_dto(db,project,issue)


def retire(db,project,user,body,requirement_id):
    logical=b.requirement(db,project.id,requirement_id)
    latest=b.latest_revision(db,requirement_id)
    if latest.revision_no!=body.expected_revision_no or logical.retired==body.retired:
        b.fail(409,"要求状态或版本已变化，请刷新。")
    if body.retired and db.scalar(select(m.ReviewIssue.id).where(m.ReviewIssue.requirement_id==logical.id,
            m.ReviewIssue.withdrawn==False)):
        # Accepted issues are also retained: withdraw explicitly so future restoration has a clear owner.
        b.fail(409,"请先明确撤销该要求下的问题，再退休要求；历史记录不会删除。")
    logical.retired=body.retired;logical.review_version+=1
    if body.retired:
        for impact in db.scalars(select(m.ChangeImpact).where(m.ChangeImpact.requirement_id==logical.id,
                m.ChangeImpact.disposition=="PENDING")):
            impact.disposition="RETIRED";impact.reviewed_by=user.id;impact.review_note=body.note;impact.version+=1
    audit(db,project,user,"REQUIREMENT_LIFECYCLE_CHANGED",logical.id,{"retired":body.retired,"note":body.note})
    db.flush();return {"requirement_id":logical.id,"retired":logical.retired,"revision_no":latest.revision_no}


def remove_member(db,project,user,body,user_id):
    member=db.get(m.ProjectMember,(project.id,user_id))
    if not member:b.fail(404,"项目成员不存在。")
    if member.role=="OWNER":b.fail(409,"不能移除负责人。")
    if db.scalar(select(m.WorkItem.id).where(m.WorkItem.project_id==project.id,m.WorkItem.assignee_id==user_id,
            m.WorkItem.status!="CANCELLED")):
        b.fail(409,"该成员仍有任务，请先转派或撤销。")
    db.delete(member)
    audit(db,project,user,"PROJECT_MEMBER_REMOVED",user_id,{"note":body.note})
    return {"user_id":user_id,"removed":True}


def create_impact(db,project,user,body):
    logical=b.requirement(db,project.id,body.requirement_id)
    if logical.retired:b.fail(409,"请先恢复要求。")
    sources=b.sources(db,project,body.sources,tender=True)
    if any(s["document_kind"]!="AMENDMENT" for s in sources):b.fail(422,"更正影响必须引用更正文件。")
    logical.review_version+=1
    impact=m.ChangeImpact(project_id=project.id,requirement_id=logical.id,source=sources,note=body.note,created_by=user.id)
    db.add(impact);db.flush()
    return impact_dto(impact)


def impact_dto(row):
    return {k:getattr(row,k) for k in ("id","requirement_id","source","note","disposition","version",
        "created_by","reviewed_by","review_note","created_at")}


def decide_impact(db,project,user,body,impact_id):
    row=db.get(m.ChangeImpact,impact_id)
    if not row or row.project_id!=project.id:b.fail(404,"更正影响记录不存在。")
    if row.version!=body.expected_version or row.disposition!="PENDING":b.fail(409,"更正影响已处理，请刷新。")
    latest=b.latest_revision(db,row.requirement_id)
    if body.disposition=="REVISED":
        allowed={s["artifact_id"] for s in row.source}
        if latest.status!="CONFIRMED" or not any(s["artifact_id"] in allowed for s in latest.sources):
            b.fail(409,"请先依据该更正修订并确认要求，保留更正出处。")
    row.disposition=body.disposition;row.reviewed_by=user.id;row.review_note=body.note;row.version+=1
    db.get(m.Requirement,row.requirement_id).review_version+=1
    audit(db,project,user,"AMENDMENT_IMPACT_REVIEWED",row.id,{"disposition":body.disposition,"note":body.note})
    return impact_dto(row)


def notify_mutation(db,project,user,operation,response):
    action=operation.split(":")[0]
    recipients=set();title=None;section="tasks"
    if action in {"CREATE_ISSUE","REASSIGN_TASK","TRANSITION_TASK","DECIDE_TASK","WITHDRAW_ISSUE","ADOPT_ASSISTANT"}:
        task=response.get("task",response)
        if task.get("status")=="SUBMITTED":
            recipients={mid for mid,role in db.execute(select(m.ProjectMember.user_id,m.ProjectMember.role)
                .where(m.ProjectMember.project_id==project.id)) if role in b.REVIEW}
            title="有整改提交等待独立复核"
        else:
            if task.get("assignee_id"):recipients.add(task["assignee_id"])
            title="你的整改任务有新的指派或处理结果"
    elif action in {"PUBLISH_BASELINE","PUBLISH_MATERIAL_SET","CREATE_CHANGE_IMPACT"}:
        recipients=set(db.scalars(select(m.ProjectMember.user_id).where(m.ProjectMember.project_id==project.id)))
        title="项目审查依据或更正影响已更新";section="changes" if action=="CREATE_CHANGE_IMPACT" else "overview"
    if title:
        db.add_all(m.Notification(project_id=project.id,user_id=recipient,title=title,section=section)
            for recipient in recipients-{user.id})
