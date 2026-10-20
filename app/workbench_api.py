"""真实项目网页所需的会话与聚合读取；业务写入继续使用原有接口。"""
from datetime import datetime, timedelta
import secrets

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import select

from app import business as b, business_api as api, business_schemas as s, models as m
from app.api_docs import error_responses
from app.dependencies import CurrentUser, DB, ProjectID
from app.session_auth import COOKIE_NAME, same_origin
from app.storage import sha256

router = APIRouter(prefix="/api/v1", tags=["07 成员与工作台"])


class LoginInput(BaseModel):
    api_key: SecretStr = Field(description="已有账号的访问密钥，只在本次登录请求传输。不得写入网址或浏览器本地存储；管理员通过 CLI 创建账号。")


class SessionResponse(BaseModel):
    user: s.MeResponse = Field(description="本次实际登录用户，不包含 API Key 或摘要。")
    expires_at: datetime | None = Field(description="Cookie 会话的 UTC 到期时间；仅使用 API Key 查询时为空。")


class LogoutResponse(BaseModel):
    logged_out: bool = Field(description="当前浏览器会话已撤销，其他设备会话不受影响。")


class FileRevision(BaseModel):
    id: str = Field(description="不可变文件修订 ID，可用于打开原 PDF。")
    revision_no: int = Field(description="该文档的修订序号，从 1 开始。")
    created_at: datetime = Field(description="UTC 上传时间。")
    byte_size: int = Field(description="原 PDF 字节数。")
    status: str = Field(description="文档修订处理状态；完整后台进度见 job_status。")
    job_id: str | None = Field(description="该修订最近创建的解析任务 ID。")
    job_status: str | None = Field(description="后台任务状态，成功才可选择文字出处。")
    error_detail: str | None = Field(description="处理失败的原因，未失败时可为空。")
    artifact_id: str | None = Field(description="成功解析后的产物 ID，选原文和正式材料时使用。")
    page_count: int | None = Field(description="解析取得的 PDF 总页数。")
    block_count: int | None = Field(description="解析取得的文字块数。零文字需检查扫描件情况。")


class ProjectFile(BaseModel):
    id: str = Field(description="逻辑文档 ID，新版上传到此文档而非覆盖旧字节。")
    title: str = Field(description="文档显示名称。")
    kind: str = Field(description="TENDER 招标、AMENDMENT 更正、RESPONSE 响应、EVIDENCE 证明。")
    revisions: list[FileRevision] = Field(description="文件修订，按版本从新到旧排序。")


class WorkbenchResponse(BaseModel):
    workspace: s.WorkspaceResponse = Field(description="项目名称、当前输入版本与登录人的权限。")
    documents: list[ProjectFile] = Field(description="本项目资料及历史修订和解析进度；不会混入其他项目。")
    requirements: list[s.RequirementResponse] = Field(description="每条要求的最新录入版，可能尚未进入当前基线。")
    baseline: s.BaselineResponse | None = Field(description="实际审查的当前冻结要求，尚未发布则为空。")
    material_set: s.MaterialSetResponse | None = Field(description="本轮正式材料快照，上传新文件不会自动替换它。")
    issues: list[s.IssueResponse] = Field(description="历史问题、对应任务和版本失效状态。")
    members: list[s.MemberResponse] = Field(description="本项目成员和角色，用于指派和显示实际操作人。")
    report: s.ReviewReportResponse = Field(description="在同一数据库读取事务中生成的当前人工覆盖报告。")


@router.post("/auth/session", operation_id="login_browser", summary="使用已有账号密钥登录网页",
    response_model=SessionResponse, responses=error_responses(401, 403, 422),
    description="**业务场景**：用户进入我的项目工作台，先确认实际操作身份。管理员事先通过 CLI 创建账号并提供访问密钥。服务端验证后仅在浏览器设置随机 HttpOnly、SameSite=Strict 会话 Cookie，数据库只存其摘要，有效期七天。重复登录撤销此浏览器原会话。请求须来自本站；不创建账号、不返回或保存原始密钥。后续网页写入还会检查 Origin；API Key 接口调用保持兼容。")
def login(body: LoginInput, request: Request, response: Response, db: DB):
    same_origin(request)
    key = body.api_key.get_secret_value()
    user = db.scalar(select(m.User).where(m.User.api_key_hash == sha256(key.encode()))) if 24 <= len(key) <= 256 else None
    if user is None:
        raise HTTPException(401, "访问密钥不正确，请核对账号配置。")
    old = request.cookies.get(COOKIE_NAME)
    if old:
        session = db.scalar(select(m.WebSession).where(m.WebSession.token_hash == sha256(old.encode())))
        if session:
            db.delete(session)
    token = secrets.token_urlsafe(48)
    expires = m.utcnow() + timedelta(days=7)
    db.add(m.WebSession(token_hash=sha256(token.encode()), user_id=user.id, expires_at=expires))
    db.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=7 * 86400, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"user": {"id": user.id, "name": user.name}, "expires_at": expires}


@router.get("/auth/session", operation_id="get_browser_session", summary="恢复网页当前登录身份",
    response_model=SessionResponse, responses=error_responses(401),
    description="**业务场景**：刷新或重新打开工作台后，网页检查当前账号，不必反复输入访问密钥。有效 Cookie 或 X-API-Key 均可认证；返回当前账号名称和浏览器会话到期时间，不暴露密钥及 Cookie 令牌。会话到期返回 401，页面应回到登录页。此接口不会延长会话，也不会授予任何项目权限；项目可见范围仍取决于项目成员表。API Key 调用没有对应 Cookie 时到期时间为空。")
def current_session(request: Request, response: Response, db: DB, user: CurrentUser):
    token = request.cookies.get(COOKIE_NAME)
    session = db.scalar(select(m.WebSession).where(m.WebSession.token_hash == sha256(token.encode()),
        m.WebSession.user_id == user.id, m.WebSession.expires_at > m.utcnow())) if token else None
    response.headers["Cache-Control"] = "no-store"
    return {"user": {"id": user.id, "name": user.name}, "expires_at": session.expires_at if session else None}


@router.delete("/auth/session", operation_id="logout_browser", summary="退出并撤销当前浏览器会话",
    response_model=LogoutResponse, responses=error_responses(403),
    description="**业务场景**：交接电脑或切换账号时退出工作台。仅撤销请求 Cookie 对应的服务端会话并清除浏览器 Cookie，其他浏览器会话和 API Key 不变。已经退出或会话过期也可再次调用并返回成功；必须带本站 Origin 以防第三方页面触发退出。下一次进入受保护页面需要重新登录。此操作不删除项目、文件、历史审查记录，也不会改变成员角色。")
def logout(request: Request, response: Response, db: DB):
    same_origin(request)
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = db.scalar(select(m.WebSession).where(m.WebSession.token_hash == sha256(token.encode())))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return {"logged_out": True}


@router.get("/projects/{project_id}/workbench", operation_id="get_project_workbench", summary="读取真实项目完整工作台",
    response_model=WorkbenchResponse, responses=error_responses(401, 404),
    description="**业务场景**：打开一个项目，同时查看资料解析状态、最新要求、实际审查基线、正式材料、问题任务及报告。仅项目成员可读；不属于项目返回 404。内容在同一数据库读取事务内整理，区分最新草稿与冻结基线，保留文件历史修订并标明任务进度。此接口只读，不自动发布材料或要求，也不执行模型判断。后续写入继续使用原业务接口并携带工作台所见的 epoch、任务版本和幂等键。")
def workbench(project_id: ProjectID, db: DB, user: CurrentUser, response: Response):
    project, _ = b.access(db, project_id, user)
    files = []
    for doc in db.scalars(select(m.Document).where(m.Document.project_id == project_id).order_by(m.Document.created_at, m.Document.id)):
        revisions = []
        for rev in db.scalars(select(m.DocumentRevision).where(m.DocumentRevision.document_id == doc.id).order_by(m.DocumentRevision.revision_no.desc())):
            job = db.scalar(select(m.Job).where(m.Job.revision_id == rev.id).order_by(m.Job.created_at.desc(), m.Job.id).limit(1))
            artifact = db.get(m.ParseArtifact, job.artifact_id) if job and job.artifact_id else None
            revisions.append({"id": rev.id, "revision_no": rev.revision_no, "created_at": rev.created_at,
                "byte_size": rev.byte_size, "status": rev.status, "job_id": job.id if job else None,
                "job_status": job.status if job else None, "error_detail": job.error_detail if job else None,
                "artifact_id": artifact.id if artifact else None, "page_count": artifact.page_count if artifact else None,
                "block_count": artifact.block_count if artifact else None})
        files.append({"id": doc.id, "title": doc.title, "kind": doc.kind, "revisions": revisions})
    response.headers["Cache-Control"] = "no-store"
    return {"workspace": api.workspace(project_id, db, user), "documents": files,
        "requirements": api.requirements(project_id, db, user),
        "baseline": b.baseline_dto(db, db.get(m.Baseline, project.current_baseline_id)) if project.current_baseline_id else None,
        "material_set": b.dto(s.MaterialSetResponse, db.get(m.MaterialSet, project.current_material_set_id)) if project.current_material_set_id else None,
        "issues": api.issues(project_id, db, user), "members": api.members(project_id, db, user), "report": b.report(db, project)}


@router.get("/projects/{project_id}/member-candidates", operation_id="find_member_candidates", summary="按姓名查找可加入项目的已有账号",
    response_model=list[s.MeResponse], responses=error_responses(401, 403, 404, 422),
    description="**业务场景**：负责人邀请编写人或复核人加入项目，页面按姓名查找管理员已创建的账号，避免人工填写用户 ID。仅本项目 OWNER 可以查询；至少输入两个字符，最多返回三十名。排除已有成员与演示工作区虚拟人物，只返回姓名和 ID，不返回任何访问密钥。选择账号后调用设置成员接口指定角色；找不到账号时应先由管理员通过 CLI 创建，查询本身不会创建或授权账号。")
def candidates(project_id: ProjectID, db: DB, user: CurrentUser,
               q: str = Query(min_length=2, max_length=80, description="目标账号姓名的一部分，按字面包含匹配。")):
    _, member = b.access(db, project_id, user)
    if member.role != "OWNER":
        raise HTTPException(403, "Only the owner can search accounts")
    if len(q.strip()) < 2:
        raise HTTPException(422, "姓名至少需要两个非空白字符。")
    existing = select(m.ProjectMember.user_id).where(m.ProjectMember.project_id == project_id)
    demo_ids = select(m.DemoWorkspace.owner_id).union(select(m.DemoWorkspace.editor_id), select(m.DemoWorkspace.reviewer_id))
    users = db.scalars(select(m.User).where(m.User.name.contains(q.strip(), autoescape=True),
        m.User.id.not_in(existing), m.User.id.not_in(demo_ids)).order_by(m.User.name, m.User.id).limit(30))
    return [{"id": u.id, "name": u.name} for u in users]


@router.get("/projects/{project_id}/review-report/export", operation_id="export_project_report", summary="下载当前人工审查报告 Markdown",
    response_class=Response, responses={**error_responses(401, 404), 200: {"description": "UTF-8 Markdown 文件，含当前范围、要求出处、判断和问题。", "content": {"text/markdown": {"schema": {"type": "string"}}}}},
    description="**业务场景**：负责人需要将本轮人工核对结果保存到本地或交给同事阅读。仅项目成员可下载，报告始终从当前基线、正式材料与有效决定生成，明确列出未完成项和未发布要求变化，不把没有问题当作审查通过。包含冻结文件版本、原件摘要、招标出处、人工意见和证据，便于追溯；不包含访问密钥。导出是当前时点快照，不会锁定后续修改，也不构成模型自动审查或法律合规保证。")
def export_report(project_id: ProjectID, db: DB, user: CurrentUser):
    project, _ = b.access(db, project_id, user)
    report = b.report(db, project)
    names = {u.id: u.name for u in db.scalars(select(m.User).join(m.ProjectMember).where(m.ProjectMember.project_id == project_id))}
    # User text is escaped as plain Markdown text so source content cannot inject links/HTML.
    def plain(value):
        text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for char in "\\`*_{}[]()#+!|":
            text = text.replace(char, "\\" + char)
        return text
    def quotes(refs):
        return [f"> 第 {ref['page']} 页：{plain(ref['quote']).replace(chr(10), chr(10) + '> ')}\n> 原件 SHA-256：{ref['revision_sha256']}" for ref in refs]
    status = {"NOT_READY": "尚未准备好审查输入", "ISSUES_OPEN": "有未解决问题", "IN_REVIEW": "核对中", "REVIEW_COMPLETE": "本轮人工核对完成"}
    row_status = {"REVIEWED": "已人工确认", "ISSUES_OPEN": "待整改", "NEEDS_REVIEW": "待最终确认", "UNREVIEWED": "未核对"}
    lines = [f"# {plain(project.name)}：人工审查报告", "", f"生成时间（UTC）：{m.utcnow().isoformat(timespec='seconds')}",
        f"状态：{status[report['status']]}；当前覆盖：{report['reviewed_count']}/{report['requirement_count']}；未解决问题：{report['unresolved_issue_count']}",
        f"尚有未发布要求变化：{'是' if report['pending_requirement_changes'] else '否'}", "", "本报告由人工核对形成，系统未执行模型自动审查。", ""]
    if project.current_material_set_id:
        material = db.get(m.MaterialSet, project.current_material_set_id)
        lines += [f"## 正式材料集第 {material.version} 版", ""]
        for item in material.items:
            lines += [f"- {plain(item['title'])} · {item['submission_role']} · 修订 {item['revision_id']} · SHA-256 {item['sha256']}"]
    if project.current_baseline_id:
        baseline = b.baseline_dto(db, db.get(m.Baseline, project.current_baseline_id))
        lines += ["", f"## 要求基线第 {baseline['version']} 版", ""]
        frozen = {r['requirement_id']: r for r in baseline['requirements']}
        for row in report['requirements']:
            req = frozen[row['requirement_id']]
            lines += [f"### {plain(req['title'])}", "", plain(req['text']), "", f"状态：{row_status[row['status']]}", "", *quotes(req['sources']), ""]
            decision = row['current_decision']
            if decision:
                lines += [f"审核人：{plain(names.get(decision['decided_by'], '历史成员'))}；意见：{plain(decision['note'])}", "", *quotes(decision['evidence']), ""]
    lines += ["## 问题与整改", ""]
    for issue in api.issues(project_id, db, user):
        task = issue['task']
        lines += [f"### {plain(issue['title'])}", "", plain(issue['description']),
            f"状态：{issue['status']}；负责人：{plain(names.get(task['assignee_id'], '历史成员'))}", "", *quotes(issue['evidence']), ""]
        if task['current_submission']:
            submission = task['current_submission']
            lines += [f"最近提交：{plain(submission['note'])}", "", *quotes(submission['evidence']), ""]
        for decision in task['decisions']:
            lines += [f"复核：{decision['decision']}；{plain(names.get(decision['decided_by'], '历史成员'))}；{plain(decision['note'])}", ""]
    return Response("\n\n".join(lines), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="review-report.md"', "Cache-Control": "no-store"})
