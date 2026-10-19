"""有边界的产品体验适配层：只代理演示 Cookie 自己的隔离项目，不接受外部项目 ID。"""
import re
import secrets
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import business as b
from app import business_schemas as s
from app import models as m
from app.config import get_settings
from app.database import utcnow
from app.dependencies import DB
from app.jobs import run_job
from app.services import ingest_pdf
from app.storage import BlobStore, sha256

router = APIRouter(prefix="/demo/api", include_in_schema=False)
COOKIE = "bid_demo_session"
ASSETS = Path(__file__).parent / "demo_assets"
SPEC = [
    ("响应时限", "响应时限：", "接报后2小时内响应", "响应时限关系到是否能及时处理故障。", "TECHNICAL"),
    ("操作培训", "培训服务：", "至少提供2次培训", "交付后，使用方的工作人员需要学会操作系统。", "DELIVERY"),
    ("驻场工程师", "驻场人员：", "至少安排1名工程师", "驻场就是安排人员到客户现场提供服务。", "DELIVERY"),
]


class StartInput(BaseModel):
    reset: bool = False


class ActionInput(BaseModel):
    expected_epoch: int = Field(ge=0)
    expected_material_set_id: str
    expected_task_version: int | None = Field(default=None, ge=1)
    submission_id: str | None = None
    note: str = Field(default="", max_length=2000)
    hours: Literal[2, 4] = 2
    decision: Literal["ACCEPT", "RETURN"] = "ACCEPT"
    requirement_ids: list[str] = Field(default_factory=list, max_length=3)


def gate(request):
    if not get_settings().demo_enabled:
        raise HTTPException(404, "演示入口未启用")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "请在本演示页面内操作")


def session(db, request, required=True):
    gate(request)
    token = request.cookies.get(COOKIE, "")
    row = db.scalar(select(m.DemoWorkspace).where(m.DemoWorkspace.token_hash == sha256(token.encode()),
                                                m.DemoWorkspace.expires_at > utcnow())) if token else None
    if row is None and required:
        raise HTTPException(401, "请先开始体验，演示进度会自动保存")
    return row


def parse_upload(db, user, project_id, filename, key, *, document_id=None):
    settings = get_settings()
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    db.commit()  # Never carry an earlier read snapshot into upload's locking reads.
    result = ingest_pdf(db, BlobStore(settings.storage_path), user, project_id,
        (ASSETS / filename).read_bytes(), "项目招标文件.pdf" if filename == "tender.pdf" else "技术响应书.pdf",
        "TENDER" if filename == "tender.pdf" else "RESPONSE", key, settings.parser_profile, document_id=document_id)
    run_job(factory, result["job_id"], settings)
    # A real dispatcher may have claimed this job first. Wait for its result without holding a DB snapshot.
    for _ in range(100):
        with factory() as fresh:
            job = fresh.get(m.Job, result["job_id"])
            if job.status == "SUCCEEDED":
                return {**result, "artifact_id": job.artifact_id}
            if job.status == "FAILED":
                raise HTTPException(503, "演示文件解析失败，请稍后重试")
        time.sleep(.1)
    raise HTTPException(503, "后台正在处理文件，请稍后重试本次操作")


def block_for(db, artifact_id, prefix):
    return next(row for row in db.scalars(select(m.DocumentBlock).where(
        m.DocumentBlock.artifact_id == artifact_id).order_by(m.DocumentBlock.block_id)) if row.text.startswith(prefix))


def reference(block):
    return {"artifact_id": block.artifact_id, "block_id": block.block_id}


def create_workspace(db):
    token = secrets.token_urlsafe(36)
    actors = [m.User(name=name, api_key_hash=sha256(secrets.token_bytes(36))) for name in ("周经理", "陈工", "林悦")]
    db.add_all(actors)
    db.flush()
    owner, editor, reviewer = actors
    project = m.Project(name="城市服务平台运维项目")
    db.add(project)
    db.flush()
    db.add_all([m.ProjectMember(project_id=project.id, user_id=user.id, role=role)
                for user, role in zip(actors, ("OWNER", "EDITOR", "REVIEWER"))])
    db.commit()
    tender = parse_upload(db, editor, project.id, "tender.pdf", str(uuid.uuid4()))
    response = parse_upload(db, editor, project.id, "response-4h.pdf", str(uuid.uuid4()))
    requirements = []
    for title, prefix, _, _, category in SPEC:
        block = block_for(db, tender["artifact_id"], prefix)
        body = s.RequirementInput(title=title, text=block.text, category=category,
                                  priority="MANDATORY", sources=[reference(block)])
        req = b.mutate(db, editor, project.id, str(uuid.uuid4()), body, "CREATE_REQUIREMENT", b.EDIT, b.create_requirement)
        b.mutate(db, reviewer, project.id, str(uuid.uuid4()), s.ConfirmRequirementInput(expected_revision_no=1),
            "CONFIRM_REQUIREMENT:" + req["requirement_id"], b.REVIEW,
            lambda d, p, u, v: b.confirm_requirement(d, p, u, v, req["requirement_id"]))
        requirements.append(req)
    b.mutate(db, reviewer, project.id, str(uuid.uuid4()), s.BaselineInput(name="演示要求确认版", expected_epoch=0,
        requirement_revision_ids=[req["revision_id"] for req in requirements]), "PUBLISH_BASELINE", b.REVIEW, b.publish_baseline)
    b.mutate(db, editor, project.id, str(uuid.uuid4()), s.MaterialSetInput(name="首次响应书", expected_epoch=1,
        items=[{"artifact_id": response["artifact_id"], "submission_role": "FORMAL_RESPONSE"}]),
        "PUBLISH_MATERIAL_SET", b.EDIT, b.publish_materials)
    row = m.DemoWorkspace(token_hash=sha256(token.encode()), project_id=project.id, owner_id=owner.id,
        editor_id=editor.id, reviewer_id=reviewer.id, context={"requirement_ids": [r["requirement_id"] for r in requirements],
            "response_document_id": response["document_id"], "tender_document_id": tender["document_id"]},
        expires_at=utcnow() + timedelta(days=7))
    db.add(row)
    db.commit()
    return row, token


def issue_for(db, demo):
    return db.scalar(select(m.ReviewIssue).where(m.ReviewIssue.project_id == demo.project_id,
        m.ReviewIssue.requirement_id == demo.context["requirement_ids"][0]).order_by(m.ReviewIssue.created_at).limit(1))


def response_artifact(db, project):
    materials = db.get(m.MaterialSet, project.current_material_set_id)
    return next(item["artifact_id"] for item in materials.items if item["submission_role"] == "FORMAL_RESPONSE")


def source_dto(db, project, block):
    artifact, revision, document = b.artifact_parts(db, project.id, block.artifact_id)
    return {"artifact_id": artifact.id, "block_id": block.block_id, "revision_id": revision.id,
        "quote": block.text, "page": block.page, "bbox": block.bbox, "filename": document.title,
        "revision_no": revision.revision_no, "original_url": f"/demo/api/originals/{revision.id}"}


def state(db, demo):
    project = db.get(m.Project, demo.project_id, populate_existing=True)
    report = b.report(db, project)
    row_reports = {row["requirement_id"]: row for row in report["requirements"]}
    current = response_artifact(db, project)
    rows = []
    for index, requirement_id in enumerate(demo.context["requirement_ids"]):
        revision = b.latest_revision(db, requirement_id)
        title, prefix, target, explanation, _ = SPEC[index]
        response_block = block_for(db, current, prefix)
        source = revision.sources[0]
        tender_block = db.get(m.DocumentBlock, (source["artifact_id"], source["block_id"]))
        rows.append({"id": requirement_id, "revision_id": revision.id, "number": f"{index+1:02d}",
            "title": title, "target": target, "explanation": explanation,
            "tender": source_dto(db, project, tender_block), "response": source_dto(db, project, response_block),
            "report": row_reports[requirement_id]})
    hours = int(re.search(r"在(\d+)小时", rows[0]["response"]["quote"]).group(1))
    issue = issue_for(db, demo)
    issue_data = b.issue_dto(db, project, issue) if issue else None
    revisions = db.scalars(select(m.DocumentRevision).where(
        m.DocumentRevision.document_id == demo.context["response_document_id"]).order_by(m.DocumentRevision.revision_no))
    actions = {"CREATE_ISSUE": "登记了响应时限问题", "TRANSITION_TASK": "更新了整改任务",
               "DECIDE_TASK": "完成了一次整改复核", "DECIDE_REQUIREMENT": "记录了逐项审核决定",
               "PUBLISH_MATERIAL_SET": "确定了本轮使用的响应文件"}
    events = db.scalars(select(m.AuditEvent).where(m.AuditEvent.project_id == project.id,
        m.AuditEvent.action.in_(actions)).order_by(m.AuditEvent.created_at, m.AuditEvent.id))
    history = [{"id": event.id, "actor": db.get(m.User, event.actor_id).name,
                "text": actions[event.action], "at": event.created_at} for event in events]
    return {"project": {"name": project.name, "subtitle": "服务商的投标文件检查", "demo": True},
        "actors": [{"key": "reviewer", "name": "林悦", "title": "审查人", "description": "对照要求、登记问题、复核整改"},
                   {"key": "editor", "name": "陈工", "title": "编写人", "description": "修改响应文件、提交整改"}],
        "requirements": rows, "issue": issue_data, "report": report, "hours": hours,
        "versions": {"epoch": project.review_epoch, "material_set_id": project.current_material_set_id},
        "files": [{"revision_id": revision.id, "version": revision.revision_no, "created_at": revision.created_at,
                   "original_url": f"/demo/api/originals/{revision.id}"} for revision in revisions], "history": history}


@router.post("/session")
def start(body: StartInput, request: Request, response: Response, db: DB):
    demo = session(db, request, required=False)
    if demo is None or body.reset:
        demo, token = create_workspace(db)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=7*24*3600, path="/demo")
    response.headers["Cache-Control"] = "no-store"
    return state(db, demo)


@router.get("/session")
def get_session(request: Request, response: Response, db: DB):
    response.headers["Cache-Control"] = "no-store"
    return state(db, session(db, request))


@router.post("/actions/{action}")
def act(action: str, body: ActionInput, request: Request, db: DB,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=80)],
        actor: Annotated[Literal["editor", "reviewer"], Header(alias="X-Demo-Actor")]):
    demo = session(db, request)
    allowed = {"open-issue": "reviewer", "start": "editor", "submit": "editor", "review": "reviewer",
               "confirm": "reviewer", "new-version": "editor"}
    if action not in allowed:
        raise HTTPException(404, "没有这个演示动作")
    if actor != allowed[action]:
        raise HTTPException(403, "请切换到这一步对应的演示角色")
    user = db.get(m.User, demo.editor_id if actor == "editor" else demo.reviewer_id)
    project = db.get(m.Project, demo.project_id)
    issue = issue_for(db, demo)
    task = db.scalar(select(m.WorkItem).where(m.WorkItem.issue_id == issue.id)) if issue else None
    first_id = demo.context["requirement_ids"][0]
    revision = b.latest_revision(db, first_id)
    current = response_artifact(db, project)
    def mutate(payload, operation, roles, handler, suffix=""):
        return b.mutate(db, user, project.id, key + suffix, payload, operation, roles, handler)

    if action == "open-issue":
        payload = s.IssueInput(expected_epoch=body.expected_epoch, requirement_revision_id=revision.id,
            title="响应4小时与招标2小时冲突", description=body.note.strip() or "招标要求2小时内响应，正式响应书写了4小时，请核对并修正。",
            kind="CONFLICT", severity="HIGH", assignee_id=demo.editor_id,
            evidence=[reference(block_for(db, current, SPEC[0][1]))])
        def one_issue(d, p, u, value):
            prior = issue_for(d, demo)
            return b.issue_dto(d, p, prior) if prior else b.create_issue(d, p, u, value)
        mutate(payload, "CREATE_ISSUE", b.REVIEW, one_issue)
    elif action in {"start", "submit", "review"} and task is None:
        raise HTTPException(409, "先登记问题，再开始整改")
    elif action == "start":
        payload = s.TaskTransitionInput(action="START", expected_version=body.expected_task_version or 1,
                                       expected_epoch=body.expected_epoch)
        mutate(payload, f"TRANSITION_TASK:{task.id}", b.EDIT,
               lambda d, p, u, value: b.transition_task(d, p, u, value, task.id))
    elif action in {"submit", "new-version"}:
        def preflight(d, p, u, value):
            b.check_epoch(p, value.expected_epoch)
            if value.expected_material_set_id != p.current_material_set_id:
                raise HTTPException(409, "本轮材料已变更，请刷新后核对")
            if action == "submit":
                current_task = b.get_task(d, p.id, task.id)
                if current_task.status != "IN_PROGRESS" or current_task.version != value.expected_task_version:
                    raise HTTPException(409, "任务已变更，请刷新并先开始整改")
            elif not b.report(d, p)["manual_review_complete"]:
                raise HTTPException(409, "先完成本轮检查，再体验文件再次更新")
            return {"id": p.id}
        mutate(body, "DEMO_WRITE_CHECK", b.EDIT, preflight, "-check")
        filename = "response-2h-v3.pdf" if action == "new-version" else f"response-{body.hours}h.pdf"
        if action == "submit" and body.hours == 2:
            active = db.get(m.ParseArtifact, current)
            active_revision = db.get(m.DocumentRevision, active.revision_id)
            if active_revision.sha256 == sha256((ASSETS / "response-2h-v3.pdf").read_bytes()):
                filename = "response-2h-v3.pdf"  # Recheck the current file; never silently revert the layout edition.
        uploaded = parse_upload(db, user, project.id, filename, key + "-file", document_id=demo.context["response_document_id"])
        material_body = s.MaterialSetInput(name="整改后正式响应" if action == "submit" else "排版校对版响应",
            expected_epoch=body.expected_epoch, expected_current_material_set_id=body.expected_material_set_id,
            items=[{"artifact_id": uploaded["artifact_id"], "submission_role": "FORMAL_RESPONSE"}])
        mutate(material_body, "PUBLISH_MATERIAL_SET", b.EDIT, b.publish_materials, "-materials")
        if action == "submit":
            payload = s.TaskTransitionInput(action="SUBMIT", expected_version=body.expected_task_version or 1,
                expected_epoch=body.expected_epoch + 1, note=body.note.strip() or f"已核对响应文件，当前承诺为{body.hours}小时，提交复核。",
                evidence=[reference(block_for(db, uploaded["artifact_id"], SPEC[0][1]))])
            mutate(payload, f"TRANSITION_TASK:{task.id}", b.EDIT,
                   lambda d, p, u, value: b.transition_task(d, p, u, value, task.id), "-submit")
    elif action == "review":
        payload = s.TaskDecisionInput(expected_version=body.expected_task_version or 1,
            submission_id=body.submission_id or "", decision=body.decision,
            note=body.note.strip() or ("已回看本次正式文件，确认响应承诺满足2小时要求。" if body.decision == "ACCEPT" else "原文仍不满足要求，请继续修改。"))
        mutate(payload, f"DECIDE_TASK:{task.id}", b.REVIEW,
               lambda d, p, u, value: (b.check_epoch(p, body.expected_epoch), b.decide_task(d, p, u, value, task.id))[1], "-review")
        if body.decision == "ACCEPT":
            payload = s.RequirementDecisionInput(expected_epoch=body.expected_epoch, requirement_revision_id=revision.id,
                decision="CONFIRMED_SATISFIED", note="人工验收整改后，确认本项响应满足要求。",
                evidence=[reference(block_for(db, current, SPEC[0][1]))])
            mutate(payload, "DECIDE_REQUIREMENT", b.REVIEW, b.decide_requirement, "-final")
    elif action == "confirm":
        if not body.requirement_ids or len(set(body.requirement_ids)) != len(body.requirement_ids):
            raise HTTPException(422, "请先勾选已经核对的要求")
        for requirement_id in body.requirement_ids:
            if requirement_id not in demo.context["requirement_ids"]:
                raise HTTPException(404, "演示要求不存在")
            index = demo.context["requirement_ids"].index(requirement_id)
            selected = b.latest_revision(db, requirement_id)
            payload = s.RequirementDecisionInput(expected_epoch=body.expected_epoch,
                requirement_revision_id=selected.id, decision="CONFIRMED_SATISFIED",
                note=body.note.strip() or "已对照招标原文和当前正式响应，人工确认本项满足。",
                evidence=[reference(block_for(db, current, SPEC[index][1]))])
            mutate(payload, "DECIDE_REQUIREMENT", b.REVIEW, b.decide_requirement, "-" + str(index))
    db.commit()
    return {"ok": True}


def revision_in_demo(db, demo, revision_id):
    revision = db.get(m.DocumentRevision, revision_id)
    document = db.get(m.Document, revision.document_id) if revision else None
    if not document or document.project_id != demo.project_id:
        raise HTTPException(404, "文件不存在")
    return revision, document


@router.get("/originals/{revision_id}")
def original(revision_id: str, request: Request, db: DB):
    revision, _ = revision_in_demo(db, session(db, request), revision_id)
    return FileResponse(BlobStore(get_settings().storage_path).path(revision.storage_key), media_type="application/pdf",
                        filename=f"demo-revision-{revision.revision_no}.pdf", content_disposition_type="inline")


@router.get("/documents/{revision_id}")
def document_preview(revision_id: str, request: Request, db: DB):
    demo = session(db, request)
    revision, document = revision_in_demo(db, demo, revision_id)
    artifact = db.scalar(select(m.ParseArtifact).where(m.ParseArtifact.revision_id == revision.id))
    blocks = db.scalars(select(m.DocumentBlock).where(m.DocumentBlock.artifact_id == artifact.id).order_by(m.DocumentBlock.block_id))
    return {"title": document.title, "version": revision.revision_no, "page_count": artifact.page_count,
            "blocks": [{"page": block.page, "text": block.text, "id": block.block_id} for block in blocks],
            "original_url": f"/demo/api/originals/{revision.id}"}


@router.get("/report", response_class=PlainTextResponse)
def download_report(request: Request, db: DB):
    data = state(db, session(db, request))
    statuses = {"REVIEWED": "人工确认满足", "ISSUES_OPEN": "仍有问题待处理", "UNREVIEWED": "待人工核对", "NEEDS_REVIEW": "待重新确认"}
    lines = ["# 投标文件人工检查记录（构造演示）", "", data["project"]["name"], "",
             "本记录仅为产品演示，所有文件与人物为构造样例；不是自动合规结论。", "",
             "本轮已完成" if data["report"]["manual_review_complete"] else "本轮尚未完成", ""]
    for row in data["requirements"]:
        lines.extend([f"## {row['title']}：{statuses[row['report']['status']]}", "",
            f"采购方要求：{row['tender']['quote']}", f"服务商响应：{row['response']['quote']}",
            f"来源：招标文件第{row['tender']['page']}页；技术响应书第{row['response']['page']}页，第{row['response']['revision_no']}稿。", ""])
    return PlainTextResponse("\n".join(lines), headers={"Content-Disposition": 'attachment; filename="bid-review-demo-report.md"',
                                                       "Cache-Control": "no-store"})
