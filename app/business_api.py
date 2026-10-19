"""按业务动作组织的人工审查 API；读写均通过项目成员权限隔离。"""
from fastapi import APIRouter
from sqlalchemy import func, select

from app import business as b
from app import business_schemas as s
from app import models as m
from app.api_docs import error_responses
from app.dependencies import CurrentUser, DB, ProjectID, RequirementID, TaskID, WriteKey

router = APIRouter(prefix="/api/v1")
READ_ERRORS = error_responses(401, 404, 422)
WRITE_ERRORS = error_responses(401, 403, 404, 409, 422)


def doc(scene, actor, behavior, following):
    return (f"**业务场景**：{scene}\n\n**使用人/前置条件**：{actor}\n\n"
            f"**处理与结果**：{behavior}\n\n**下一步**：{following}\n\n"
            "**调用约定**：所有接口需要 X-API-Key。写操作还需要 Idempotency-Key；网络重试沿用原键和原请求体，"
            "新业务动作换新键。404 同时表示对象不存在或不属于可访问项目。409 表示版本、状态或幂等冲突，须先刷新核对。当前所有业务判断由人完成。")


@router.get("/me", tags=["07 成员与工作台"], summary="查询我是谁，取得成员授权用的用户 ID",
    operation_id="get_me", response_model=s.MeResponse, responses=error_responses(401),
    description=doc("负责人要把同事加入投标项目，需要同事的用户 ID。", "任意已配置 API Key 的用户。",
        "返回本密钥对应的 ID 和姓名，不返回密钥本身。", "同事把自己的 ID 告知项目负责人，再由负责人添加成员。"))
def me(user: CurrentUser):
    return {"id": user.id, "name": user.name}


@router.get("/projects/{project_id}/workspace", tags=["07 成员与工作台"], summary="查看项目工作台和当前审查输入版本",
    operation_id="get_workspace", response_model=s.WorkspaceResponse, responses=READ_ERRORS,
    description=doc("进入项目后，确认当前审查哪版要求、哪套响应材料，以及自己能做什么。", "任意项目成员。",
        "返回我的角色、当前基线/材料集 ID、review_epoch、要求/问题数量和未发布修改提示；不把问题总数冒充待办数。",
        "写入前保存 review_epoch；若返回 409，刷新工作台并重新核对材料。"))
def workspace(project_id: ProjectID, db: DB, user: CurrentUser):
    project, member = b.access(db, project_id, user)
    return {"project_id": project.id, "name": project.name, "my_role": member.role,
        "review_epoch": project.review_epoch, "current_baseline_id": project.current_baseline_id,
        "current_material_set_id": project.current_material_set_id, "review_mode": "HUMAN",
        "requirement_count": db.scalar(select(func.count()).select_from(m.Requirement).where(m.Requirement.project_id == project_id)),
        "issue_count": db.scalar(select(func.count()).select_from(m.ReviewIssue).where(m.ReviewIssue.project_id == project_id)),
        "pending_requirement_changes": b.pending_changes(db, project)}


@router.get("/projects/{project_id}/members", tags=["07 成员与工作台"], summary="查看可协作的项目成员与角色",
    operation_id="list_members", response_model=list[s.MemberResponse], responses=READ_ERRORS,
    description=doc("审查人登记问题前要选择整改负责人，负责人要检查谁具有复核权限。", "任意项目成员。",
        "返回本项目成员及 OWNER/EDITOR/REVIEWER/READER 角色，不暴露其他项目成员或任何 API Key。",
        "登记问题时只能选择本项目的 OWNER 或 EDITOR 为 assignee_id。"))
def members(project_id: ProjectID, db: DB, user: CurrentUser):
    b.access(db, project_id, user)
    return [{"user_id": u.id, "name": u.name, "role": member.role} for member, u in db.execute(
        select(m.ProjectMember, m.User).join(m.User, m.User.id == m.ProjectMember.user_id)
        .where(m.ProjectMember.project_id == project_id).order_by(m.User.name, m.User.id))]


@router.post("/projects/{project_id}/members", tags=["07 成员与工作台"], summary="把已有用户加入项目或调整协作角色",
    operation_id="set_member", response_model=s.MemberResponse, responses=WRITE_ERRORS,
    description=doc("投标负责人组织编写人、审查人及只读观察者，形成责任分工。", "仅项目 OWNER；目标账号须先通过 CLI bootstrap 创建。",
        "按用户 ID 设置项目角色；不能通过本接口变更 OWNER，已有整改任务的负责人须保留 EDITOR 角色。",
        "EDITOR 录入资料和整改，REVIEWER 确认要求并复核；提交整改的人不能自己复核。"))
def set_member(project_id: ProjectID, body: s.MemberInput, db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, "SET_MEMBER", {"OWNER"}, b.set_member)


@router.post("/projects/{project_id}/requirements", status_code=201, tags=["08 要求与基线"], summary="从招标原文登记一条待确认要求",
    operation_id="create_requirement", response_model=s.RequirementResponse, responses=WRITE_ERRORS,
    description=doc("编写人读到招标文件“故障响应不得超过2小时”，把它登记为一项可核对要求。", "OWNER/EDITOR；先上传并解析招标或更正 PDF，取得原文块。",
        "创建逻辑要求和第 1 版草稿，服务端回查并冻结原文/页码/坐标/hash；客户端不能伪造引文。",
        "由 OWNER/REVIEWER 确认该要求，再发布到要求基线。"))
def create_requirement(project_id: ProjectID, body: s.RequirementInput, db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, "CREATE_REQUIREMENT", b.EDIT, b.create_requirement)


@router.get("/projects/{project_id}/requirements", tags=["08 要求与基线"], summary="查看全部要求的最新草稿或确认版",
    operation_id="list_requirements", response_model=list[s.RequirementResponse], responses=READ_ERRORS,
    description=doc("负责人检查哪些招标要求已经整理、哪些仍待确认。", "任意项目成员。",
        "每个逻辑要求只返回最新修订，包含来源和确认状态；最新草稿可能尚未纳入当前审查基线。",
        "需要知道实际审查的是哪版时，查询基线；需要修改时，携带这里的 revision_no。"))
def requirements(project_id: ProjectID, db: DB, user: CurrentUser):
    b.access(db, project_id, user)
    return [b.req_dto(row) for row in b.latest_requirements(db, project_id)]


@router.get("/projects/{project_id}/requirements/{requirement_id}/revisions", tags=["08 要求与基线"], summary="追溯一条要求的全部历史修订",
    operation_id="list_requirement_revisions", response_model=list[s.RequirementResponse], responses=READ_ERRORS,
    description=doc("更正公告改变了响应时限，需要解释原来为什么按旧要求审查。", "任意项目成员。",
        "按修订号返回正文、原始来源和确认人；旧基线和问题仍引用旧修订，不会被新正文覆盖。",
        "修改要求使用新增修订接口；新修订经确认并重新发布基线后才成为当前审查依据。"))
def requirement_revisions(project_id: ProjectID, requirement_id: RequirementID, db: DB, user: CurrentUser):
    b.access(db, project_id, user)
    b.requirement(db, project_id, requirement_id)
    return [b.req_dto(row) for row in db.scalars(select(m.RequirementRevision).where(
        m.RequirementRevision.requirement_id == requirement_id).order_by(m.RequirementRevision.revision_no))]


@router.post("/projects/{project_id}/requirements/{requirement_id}/revisions", status_code=201, tags=["08 要求与基线"],
    summary="因更正或录入错误新增要求修订", operation_id="revise_requirement", response_model=s.RequirementResponse, responses=WRITE_ERRORS,
    description=doc("招标更正或人工录入错误需要修改要求，但历史审查依据不能消失。", "OWNER/EDITOR；携带所见最新 expected_revision_no。",
        "创建新的 DRAFT 修订；旧确认、旧基线及旧结论均保留。并发修改返回 409。当前报告会提示未发布的要求变化。",
        "重新确认要求并发布新基线，旧审查决定和已验收整改会显示需重新核对。"))
def revise_requirement(project_id: ProjectID, requirement_id: RequirementID, body: s.RequirementRevisionInput,
                       db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, f"REVISE_REQUIREMENT:{requirement_id}", b.EDIT,
                    lambda d, p, u, v: b.create_requirement(d, p, u, v, requirement_id))


@router.post("/projects/{project_id}/requirements/{requirement_id}/confirm", tags=["08 要求与基线"], summary="人工确认最新要求正文及出处",
    operation_id="confirm_requirement", response_model=s.RequirementResponse, responses=WRITE_ERRORS,
    description=doc("审查人核对录入的“2小时”是否准确，有没有漏掉适用范围或例外。", "OWNER/REVIEWER；确认的是当前最新 revision_no。",
        "将最新 DRAFT 标为 CONFIRMED 并记录确认人；仅表示招标要求录入正确，不表示投标响应满足。",
        "所有要求最新修订均确认后发布基线；确认本身不会悄悄更换正在审查的版本。"))
def confirm_requirement(project_id: ProjectID, requirement_id: RequirementID, body: s.ConfirmRequirementInput,
                         db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, f"CONFIRM_REQUIREMENT:{requirement_id}", b.REVIEW,
                    lambda d, p, u, v: b.confirm_requirement(d, p, u, v, requirement_id))


@router.post("/projects/{project_id}/baselines", status_code=201, tags=["08 要求与基线"], summary="发布本次审查采用的不可变要求基线",
    operation_id="publish_baseline", response_model=s.BaselineResponse, responses=WRITE_ERRORS,
    description=doc("审查启动前，团队统一“这次到底按哪版招标要求检查”。", "OWNER/REVIEWER；全部最新要求已确认，携带工作台 epoch 和上一基线 ID。",
        "要求 ID 列表必须完整且不重复；冻结全部最新确认版，增加 review_epoch。旧基线和结论保留，但旧决定不会继续冒充当前结果。",
        "选择正式材料集，然后登记问题或逐项作出人工审核决定。"))
def publish_baseline(project_id: ProjectID, body: s.BaselineInput, db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, "PUBLISH_BASELINE", b.REVIEW, b.publish_baseline)


@router.get("/projects/{project_id}/baselines", tags=["08 要求与基线"], summary="查看历次基线及各自冻结的要求",
    operation_id="list_baselines", response_model=list[s.BaselineResponse], responses=READ_ERRORS,
    description=doc("复盘一个旧问题时，需要还原当时采用的招标要求，而不是最新草稿。", "任意项目成员。",
        "按版本递增返回基线、父基线和完整要求来源；这些内容不会被后续编辑替换。当前基线 ID 从工作台取得。",
        "对照问题中的 baseline_id 和 requirement_revision_id 还原当时依据。"))
def baselines(project_id: ProjectID, db: DB, user: CurrentUser):
    b.access(db, project_id, user)
    return [b.baseline_dto(db, row) for row in db.scalars(select(m.Baseline).where(
        m.Baseline.project_id == project_id).order_by(m.Baseline.version))]


@router.post("/projects/{project_id}/material-sets", status_code=201, tags=["09 正式响应材料"], summary="明确选择本次正式响应文件和附件",
    operation_id="publish_material_set", response_model=s.MaterialSetResponse, responses=WRITE_ERRORS,
    description=doc("资料库里既有旧响应书、模板，又有最终版；必须确定本次检查哪一套。", "OWNER/EDITOR；文件已解析，携带工作台 epoch 和上一材料集 ID。",
        "冻结修订、hash、解析配置及提交角色；至少一份正式 RESPONSE，同一逻辑文档只能选一个版本。发布会增加 epoch，旧结论需重核。",
        "审查和整改引用本材料集的原文；REFERENCE 只能辅助阅读，不能证明正式响应已满足。"))
def publish_material_set(project_id: ProjectID, body: s.MaterialSetInput, db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, "PUBLISH_MATERIAL_SET", b.EDIT, b.publish_materials)


@router.get("/projects/{project_id}/material-sets", tags=["09 正式响应材料"], summary="追溯历次审查使用的正式材料快照",
    operation_id="list_material_sets", response_model=list[s.MaterialSetResponse], responses=READ_ERRORS,
    description=doc("复核人需要确认整改提交引用的是最终响应书，而不是旧模板或事后覆盖的文件。", "任意项目成员。",
        "按版本递增返回各套材料的文件修订、原件 hash 和角色。上传新文件不会自动替换现有材料集，必须显式发布。",
        "核对任务 submission.material_set_id；如果与工作台当前值不同，重新提交整改再复核。"))
def material_sets(project_id: ProjectID, db: DB, user: CurrentUser):
    b.access(db, project_id, user)
    return [b.dto(s.MaterialSetResponse, row) for row in db.scalars(select(m.MaterialSet).where(
        m.MaterialSet.project_id == project_id).order_by(m.MaterialSet.version))]


@router.post("/projects/{project_id}/issues", status_code=201, tags=["10 问题与整改"], summary="登记一条审查问题并指派整改任务",
    operation_id="create_issue", response_model=s.IssueResponse, responses=WRITE_ERRORS,
    description=doc("审查人发现招标要求2小时，正式响应书却写4小时，需要明确问题及责任人。", "OWNER/REVIEWER；已发布当前基线和材料集，负责人是本项目 OWNER/EDITOR。",
        "冻结当时要求和证据，创建一条问题及唯一 TODO 任务。冲突必须有正式材料原文；缺失问题可无引文，但须说明核对范围。",
        "负责人查看任务，START 后修改文件，再发布新版材料集并 SUBMIT 整改。"))
def create_issue(project_id: ProjectID, body: s.IssueInput, db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, "CREATE_ISSUE", b.REVIEW, b.create_issue)


@router.get("/projects/{project_id}/issues", tags=["10 问题与整改"], summary="查看问题、整改进展及旧结论是否过期",
    operation_id="list_issues", response_model=list[s.IssueResponse], responses=READ_ERRORS,
    description=doc("项目负责人跟踪仍未解决的问题，审查人回看原始冲突依据。", "任意项目成员。",
        "返回全部历史问题和对应任务。旧问题原文保持原样；整改可引用新材料。RESOLVED 只用于当前输入已验收的结果，旧验收变为 NEEDS_RECHECK。",
        "根据任务负责人和 effective_status 推动整改；完整覆盖率查看 review-report。"))
def issues(project_id: ProjectID, db: DB, user: CurrentUser):
    project, _ = b.access(db, project_id, user)
    return [b.issue_dto(db, project, row) for row in db.scalars(select(m.ReviewIssue).where(
        m.ReviewIssue.project_id == project_id).order_by(m.ReviewIssue.created_at, m.ReviewIssue.id))]


@router.get("/projects/{project_id}/tasks", tags=["10 问题与整改"], summary="查看本项目整改待办与复核记录",
    operation_id="list_tasks", response_model=list[s.TaskResponse], responses=READ_ERRORS,
    description=doc("编写人查看自己负责哪些问题，复核人查看哪些整改已经提交。", "任意项目成员；当前首版返回项目全部任务，由 assignee_id 识别负责人。",
        "返回状态、version、最近提交和全部复核决定。effective_status 反映当前输入是否变化，持久化历史状态不被删除。",
        "负责人使用 version 发起 START/SUBMIT，复核人使用当前 submission.id 和 version 作出决定。"))
def tasks(project_id: ProjectID, db: DB, user: CurrentUser):
    project, _ = b.access(db, project_id, user)
    return [b.task_dto(db, project, row) for row in db.scalars(select(m.WorkItem).where(
        m.WorkItem.project_id == project_id).order_by(m.WorkItem.created_at, m.WorkItem.id))]


@router.get("/projects/{project_id}/tasks/{task_id}/submissions", tags=["10 问题与整改"], summary="追溯任务历次整改提交及其材料依据",
    operation_id="list_task_submissions", response_model=list[s.SubmissionResponse], responses=READ_ERRORS,
    description=doc("整改被退回或材料多次补充后，需要解释每次提交改了什么、复核的是哪一版。", "任意项目成员。",
        "按任务版本返回所有不可变提交，包含当时基线、材料集、原文引证、说明和提交人，不只返回最后一次。",
        "将提交 ID 与任务 decisions 中的 submission_id 对照，还原退回和验收过程。"))
def task_submissions(project_id: ProjectID, task_id: TaskID, db: DB, user: CurrentUser):
    b.access(db, project_id, user)
    b.get_task(db, project_id, task_id)
    return [b.dto(s.SubmissionResponse, row) for row in db.scalars(select(m.TaskSubmission).where(
        m.TaskSubmission.task_id == task_id).order_by(m.TaskSubmission.task_version))]


@router.post("/projects/{project_id}/tasks/{task_id}/transitions", tags=["10 问题与整改"], summary="负责人开始整改或提交修改后的正式证据",
    operation_id="transition_task", response_model=s.TaskResponse, responses=WRITE_ERRORS,
    description=doc("编写人接受“4小时改为2小时”的整改任务，完成修改后交给别人复核。", "仅任务负责人且仍有 OWNER/EDITOR 角色；带 expected_version 和 expected_epoch。",
        "START 将待办/退回任务转为处理中；SUBMIT 必须有说明和当前正式材料引文。过期的已提交/已验收任务也要 START 后重新提交。",
        "另一位 OWNER/REVIEWER 对 current_submission.id 作出 ACCEPT/RETURN；提交本身不等于问题解决。"))
def transition_task(project_id: ProjectID, task_id: TaskID, body: s.TaskTransitionInput,
                     db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, f"TRANSITION_TASK:{task_id}", b.EDIT,
                    lambda d, p, u, v: b.transition_task(d, p, u, v, task_id))


@router.post("/projects/{project_id}/tasks/{task_id}/decisions", tags=["10 问题与整改"], summary="由另一人复核当前整改提交，验收或退回",
    operation_id="decide_task", response_model=s.TaskResponse, responses=WRITE_ERRORS,
    description=doc("审查人重新打开修改后的响应书核对2小时承诺，决定是否通过整改。", "OWNER/REVIEWER 且不是该次整改提交人；任务必须为 SUBMITTED。",
        "校验任务 version、submission_id 及基线/材料/epoch。输入变更拒绝旧提交验收。ACCEPT 解决当前问题，RETURN 交回负责人并保留意见。",
        "问题解决后还需要逐项最终审核决定，不能把“没有未解决问题”直接当作所有要求已审查。"))
def decide_task(project_id: ProjectID, task_id: TaskID, body: s.TaskDecisionInput,
                 db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, f"DECIDE_TASK:{task_id}", b.REVIEW,
                    lambda d, p, u, v: b.decide_task(d, p, u, v, task_id))


@router.post("/projects/{project_id}/requirement-decisions", status_code=201, tags=["11 人工审查结论"], summary="对当前要求逐项记录人工最终决定",
    operation_id="decide_requirement", response_model=s.RequirementDecisionResponse, responses=WRITE_ERRORS,
    description=doc("即便没发现问题，也必须记录这条要求是否真正检查过及检查依据。", "OWNER/REVIEWER；要求在当前基线内，携带当前 epoch。",
        "确认满足须有正式材料证据且所有相关问题已由他人复核；确认有问题须先登记可整改的问题；不适用须说明理由。每次决定追加保留。",
        "查询 review-report 看逐项覆盖率。新基线或新材料发布后，旧决定保留但不再计入当前覆盖率。"))
def decide_requirement(project_id: ProjectID, body: s.RequirementDecisionInput, db: DB, user: CurrentUser, key: WriteKey):
    return b.mutate(db, user, project_id, key, body, "DECIDE_REQUIREMENT", b.REVIEW, b.decide_requirement)


@router.get("/projects/{project_id}/requirement-decisions", tags=["11 人工审查结论"], summary="查看逐项审核决定的完整历史",
    operation_id="list_requirement_decisions", response_model=list[s.RequirementDecisionResponse], responses=READ_ERRORS,
    description=doc("需求或材料变更后，需要追溯为什么上一轮认为满足、由谁确认、引用什么证据。", "任意项目成员。",
        "返回本项目所有人工决定，同一要求按 sequence 递增；包含已过期决定，不应直接累加为当前完成数量。",
        "当前有效结论及是否仍有未解决问题，以 review-report 为准；本接口用于审计和复盘。"))
def requirement_decisions(project_id: ProjectID, db: DB, user: CurrentUser):
    b.access(db, project_id, user)
    return [b.dto(s.RequirementDecisionResponse, row) for row in db.scalars(select(m.RequirementDecision)
        .join(m.Requirement, m.Requirement.id == m.RequirementDecision.requirement_id)
        .where(m.Requirement.project_id == project_id)
        .order_by(m.RequirementDecision.requirement_id, m.RequirementDecision.sequence))]


@router.get("/projects/{project_id}/review-report", tags=["11 人工审查结论"], summary="查看本轮人工审查覆盖、未解决问题和完成状态",
    operation_id="get_review_report", response_model=s.ReviewReportResponse, responses=READ_ERRORS,
    description=doc("投标负责人在提交前核实是否每条要求都有人检查，是否仍有整改未复核。", "任意项目成员。",
        "按当前基线/材料/epoch 汇总逐项结论，未登记问题不等于已审查。缺输入显示 NOT_READY，有未发布要求修改也不能显示完成。",
        "针对 UNREVIEWED/NEEDS_REVIEW 补充人工决定，针对 ISSUES_OPEN 继续整改。本报告为人工工作流状态，不是模型合规保证。"))
def review_report(project_id: ProjectID, db: DB, user: CurrentUser):
    project, _ = b.access(db, project_id, user)
    return b.report(db, project)
