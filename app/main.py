from enum import StrEnum
from pathlib import Path as FilePath
from typing import Annotated

from fastapi import FastAPI, File, Form, Header, HTTPException, Path, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.staticfiles import StaticFiles
from pydantic import HttpUrl
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api_docs import API_DESCRIPTION, DESCRIPTIONS, TAGS, error_responses
from app.config import get_settings
from app.dependencies import CurrentUser, DB
from app.business_api import router as business_router
from app.demo import router as demo_router
from app.workbench_api import router as workbench_router
from app.quality_api import router as quality_router
from app.extraction_api import router as extraction_router
from app.parse_api import router as parse_router
from app.retrieval_api import router as retrieval_router
from app.models import (AuditEvent, Document, DocumentBlock, DocumentRevision, Job,
                        ParseArtifact, Project, ProjectMember, User)
from app.services import ingest_pdf, project_access
from app.schemas import (ARTIFACT_ID, DOCUMENT_ID, JOB_ID, PROJECT_ID, REVISION_ID,
                         ArtifactResponse, BlockResponse, JobResponse, LiveResponse,
                         ProjectInput, ProjectResponse, ReadyResponse, RevisionResponse,
                         SourceResponse, UploadResponse)
from app.storage import BlobStore, sha256
from app.models import IdempotencyRecord

app = FastAPI(title="投标文件审查与资料协同系统", version="0.8.0",
              summary="可追溯的文档版本、人工要求基线、问题整改与独立复核",
              description=API_DESCRIPTION, openapi_tags=TAGS,
              swagger_ui_parameters={"filter": True, "displayRequestDuration": True,
                                     "defaultModelsExpandDepth": 1})
ProjectPath = Annotated[str, Path(description="项目 ID，从创建或列出项目接口取得；不是项目名称。", examples=[PROJECT_ID])]
DocumentPath = Annotated[str, Path(description="逻辑文档 ID，从上传新文档接口取得；多个修订共用此 ID。", examples=[DOCUMENT_ID])]
RevisionPath = Annotated[str, Path(description="不可变文件修订 ID，从上传或修订列表取得。", examples=[REVISION_ID])]
JobPath = Annotated[str, Path(description="后台任务 ID，使用上传响应的 job_id。", examples=[JOB_ID])]
ArtifactPath = Annotated[str, Path(description="解析产物 ID，使用成功任务返回的 artifact_id。", examples=[ARTIFACT_ID])]
BlockPath = Annotated[str, Path(description="当前产物内的文字块 ID，从文字块列表取得，必须与 artifact_id 配套。", examples=["p0003-b0004"])]
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128,
    description="一次上传操作的去重凭据，建议使用随机 UUID。网络重试沿用同键和同内容；业务内容改变使用新键。它不是 X-API-Key，也不是文件名。",
    examples=["6f24c7b4-5dd6-4f32-bd82-59de34224179"])]


class DocumentKind(StrEnum):
    """材料分类：TENDER 招标、AMENDMENT 更正、RESPONSE 响应、EVIDENCE 证明。"""
    TENDER = "TENDER"
    AMENDMENT = "AMENDMENT"
    RESPONSE = "RESPONSE"
    EVIDENCE = "EVIDENCE"


@app.get("/health/live", tags=["06 服务状态"], summary="检查 API 进程是否存活",
         description=DESCRIPTIONS["live"], operation_id="check_liveness",
         response_model=LiveResponse, response_description="API 能响应 HTTP；不代表数据库或 Worker 可用。")
def live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["06 服务状态"], summary="检查数据库和基础表是否就绪",
         description=DESCRIPTIONS["ready"], operation_id="check_readiness",
         response_model=ReadyResponse, responses=error_responses(503, examples={503: "Database or schema is unavailable"}),
         response_description="数据库连接及核心表查询通过；自动模型审查尚未开放。")
def ready(db: DB):
    try:
        db.execute(text("SELECT 1"))
        db.execute(select(User.id).limit(1))  # A reachable DB without migrations is not ready.
        db.execute(select(Project.current_baseline_id).limit(1))
        db.execute(text("SELECT id FROM requirement_decisions LIMIT 1"))
        db.execute(text("SELECT id FROM web_sessions LIMIT 1"))
        db.execute(text("SELECT id FROM page_quality_reviews LIMIT 1"))
        db.execute(text("SELECT id FROM extraction_runs LIMIT 1"))
        if get_settings().demo_enabled:
            db.execute(text("SELECT id FROM demo_workspaces LIMIT 1"))
    except Exception:
        raise HTTPException(503, "Database or schema is unavailable")
    return {"status": "ready", "stage": "human-review-workflow", "formal_review_ready": False}


@app.post("/api/v1/projects", status_code=201, tags=["01 项目管理"], summary="创建一次投标工作的项目空间",
          description=DESCRIPTIONS["create_project"], operation_id="create_project",
          response_model=ProjectResponse, responses=error_responses(401, 409, 422, examples={422: [
              {"type": "missing", "loc": ["body", "name"], "msg": "Field required", "input": {}}]}),
          response_description="项目已创建；返回的 id 用作后续 project_id。")
def create_project(body: ProjectInput, db: DB, user: CurrentUser,
                   key: Annotated[str | None, Header(alias="Idempotency-Key", min_length=16, max_length=128,
                       description="可选创建去重键。网页始终提供；同键同内容重试复用原项目，不同内容返回 409。旧客户端可省略。")]=None):
    scope = f"{user.id}:CREATE_PROJECT"
    request_hash = sha256(body.name.strip().encode())
    if key:
        db.commit()
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        prior = db.get(IdempotencyRecord, (scope, key))
        if prior:
            if prior.request_hash != request_hash:
                raise HTTPException(409, "Idempotency key was already used for a different request")
            result = prior.response
            db.commit()
            return result
    project = Project(name=body.name.strip())
    if not project.name:
        raise HTTPException(422, "Project name must not be blank")
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="OWNER"))
    db.add(AuditEvent(project_id=project.id, actor_id=user.id, action="PROJECT_CREATED",
                      object_id=project.id, details={}))
    result = {"id": project.id, "name": project.name}
    if key:
        db.add(IdempotencyRecord(scope=scope, key=key, request_hash=request_hash, response=result))
    db.commit()
    return result


@app.get("/api/v1/projects", tags=["01 项目管理"], summary="列出我有权限访问的项目",
         description=DESCRIPTIONS["list_projects"], operation_id="list_projects",
         response_model=list[ProjectResponse], responses=error_responses(401),
         response_description="项目数组；没有可访问项目时为 []。")
def list_projects(db: DB, user: CurrentUser):
    projects = db.scalars(select(Project).join(ProjectMember).where(ProjectMember.user_id == user.id))
    return [{"id": project.id, "name": project.name} for project in projects]


async def pdf_bytes(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_bytes
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, "File exceeds configured upload limit")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content.startswith(b"%PDF-"):
        raise HTTPException(415, "Phase 1 accepts PDF content only")
    return content


@app.post("/api/v1/projects/{project_id}/documents", status_code=202, tags=["02 文档与修订"],
          summary="上传一份新 PDF 文档并登记解析任务",
          description=DESCRIPTIONS["upload_document"], operation_id="upload_document",
          response_model=UploadResponse, responses=error_responses(401, 403, 404, 409, 413, 415, 422),
          response_description="已接收或命中幂等记录；请保存 job_id 并继续查询处理状态。")
async def upload_document(project_id: ProjectPath, db: DB, user: CurrentUser,
                          file: Annotated[UploadFile, File(description="本机选择的 PDF 文件。默认最大 50 MiB；必须是真实 PDF 内容。此阶段不接收 DOCX。")],
                          title: Annotated[str, Form(min_length=1, max_length=200, description="这份逻辑文档的显示名称，例如某项目招标文件；1–200 字符且不能为纯空白。", examples=["12345平台二期招标文件"])],
                          kind: Annotated[DocumentKind, Form(description="材料类型：TENDER 招标文件；AMENDMENT 更正公告；RESPONSE 投标响应；EVIDENCE 证明材料。更正类型当前只作分类存储。")],
                          idempotency_key: IdempotencyHeader,
                          source_url: Annotated[HttpUrl | None, Form(description="可选的 HTTP/HTTPS 来源地址，仅保存出处，不访问该地址，也不能替代 file 上传。", examples=["https://example.org/public-tender.pdf"])] = None):
    project_access(db, project_id, user, write=True)
    if not title.strip():
        raise HTTPException(422, "Document title must not be blank")
    content = await pdf_bytes(file)
    settings = get_settings()
    return await run_in_threadpool(ingest_pdf, db, BlobStore(settings.storage_path), user,
                      project_id, content, title, kind.value, idempotency_key, settings.parser_profile,
                      source_url=str(source_url) if source_url else None)


def document_access(db: Session, document_id: str, user: User, write: bool = False) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "Document not found")
    project_access(db, document.project_id, user, write=write)
    return document


@app.post("/api/v1/documents/{document_id}/revisions", status_code=202, tags=["02 文档与修订"],
          summary="为已有文档上传新 PDF 修订并保留历史",
          description=DESCRIPTIONS["upload_revision"], operation_id="upload_revision",
          response_model=UploadResponse, responses=error_responses(401, 403, 404, 409, 413, 415, 422),
          response_description="返回新修订/任务，或同文档相同字节对应的历史修订/任务。")
async def upload_revision(document_id: DocumentPath, db: DB, user: CurrentUser,
                          file: Annotated[UploadFile, File(description="这份逻辑文档的新 PDF 内容。完全相同的历史字节会复用旧修订。默认最大 50 MiB。")],
                          idempotency_key: IdempotencyHeader,
                          source_url: Annotated[HttpUrl | None, Form(description="可选的新修订来源网址，只记录出处，不下载文件。", examples=["https://example.org/revised-tender.pdf"])] = None):
    document = document_access(db, document_id, user, write=True)
    content = await pdf_bytes(file)
    settings = get_settings()
    return await run_in_threadpool(ingest_pdf, db, BlobStore(settings.storage_path), user, document.project_id, content,
                      document.title, document.kind, idempotency_key, settings.parser_profile,
                      document_id=document.id, source_url=str(source_url) if source_url else None)


@app.get("/api/v1/documents/{document_id}/revisions", tags=["02 文档与修订"],
         summary="查看一份文档的全部历史修订",
         description=DESCRIPTIONS["list_revisions"], operation_id="list_revisions",
         response_model=list[RevisionResponse], responses=error_responses(401, 404, 422),
         response_description="按 revision_no 升序返回；每条 id 都是文件修订 ID。")
def list_revisions(document_id: DocumentPath, db: DB, user: CurrentUser):
    document_access(db, document_id, user)
    revisions = db.scalars(select(DocumentRevision).where(
        DocumentRevision.document_id == document_id).order_by(DocumentRevision.revision_no))
    return [{"id": revision.id, "revision_no": revision.revision_no, "sha256": revision.sha256,
             "status": revision.status, "created_at": revision.created_at} for revision in revisions]


@app.get("/api/v1/jobs/{job_id}", tags=["03 后台任务"], summary="查询后台解析任务状态及产物 ID",
         description=DESCRIPTIONS["get_job"], operation_id="get_job",
         response_model=JobResponse, responses=error_responses(401, 404, 422),
         response_description="任务当前状态。HTTP 200 与任务自身是否成功是两回事。")
def get_job(job_id: JobPath, db: DB, user: CurrentUser):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    project_access(db, job.project_id, user)
    return {"id": job.id, "status": job.status, "attempt": job.attempt,
            "artifact_id": job.artifact_id, "error_code": job.error_code,
            "error_detail": job.error_detail, "formal_review_ready": False}


def artifact_access(db: Session, artifact_id: str, user: User) -> tuple[ParseArtifact, DocumentRevision]:
    artifact = db.get(ParseArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    revision = db.get(DocumentRevision, artifact.revision_id)
    document_access(db, revision.document_id, user)
    return artifact, revision


@app.get("/api/v1/artifacts/{artifact_id}", tags=["04 解析结果"], summary="查看解析概况、页数和质量提示",
         description=DESCRIPTIONS["get_artifact"], operation_id="get_artifact",
         response_model=ArtifactResponse, responses=error_responses(401, 404, 422),
         response_description="文字层解析产物概况；质量状态当前仍为待检查。")
def get_artifact(artifact_id: ArtifactPath, db: DB, user: CurrentUser):
    artifact, revision = artifact_access(db, artifact_id, user)
    return {"id": artifact.id, "revision_id": revision.id, "revision_sha256": revision.sha256,
            "parser_profile": artifact.parser_profile, "page_count": artifact.page_count,
            "block_count": artifact.block_count, "quality_status": artifact.quality_status,
            "quality_flags": artifact.quality_flags, "formal_review_ready": False}


@app.get("/api/v1/artifacts/{artifact_id}/blocks", tags=["04 解析结果"], summary="按页和分页条件读取文字来源块",
         description=DESCRIPTIONS["list_blocks"], operation_id="list_blocks",
         response_model=list[BlockResponse], responses=error_responses(401, 404, 422, examples={422: [
             {"type": "less_than_equal", "loc": ["query", "limit"], "msg": "Input should be less than or equal to 200", "input": "300"}]}),
         response_description="文字块数组，包含原文、实际页序和 PDF 坐标；没有匹配项返回 []。")
def list_blocks(artifact_id: ArtifactPath, db: DB, user: CurrentUser,
                page: Annotated[int | None, Query(ge=1, description="可选：只读 PDF 的某个实际页，从 1 开始。省略则跨页查询；超出页数时返回空数组。", examples=[3])] = None,
                offset: Annotated[int, Query(ge=0, description="在 page 过滤及排序后跳过的文字块数，默认 0。不是页码。", examples=[0])] = 0,
                limit: Annotated[int, Query(ge=1, le=200, description="本次最多返回的块数，默认 100，范围 1–200。下一批可将 offset 增加 limit。", examples=[100])] = 100):
    artifact_access(db, artifact_id, user)
    statement = select(DocumentBlock).where(DocumentBlock.artifact_id == artifact_id)
    if page is not None:
        statement = statement.where(DocumentBlock.page == page)
    blocks = db.scalars(statement.order_by(DocumentBlock.block_id).offset(offset).limit(limit))
    return [{"block_id": block.block_id, "page": block.page, "bbox": block.bbox,
             "text": block.text, "text_hash": block.text_hash} for block in blocks]


@app.get("/api/v1/artifacts/{artifact_id}/blocks/{block_id}/source", tags=["05 来源追溯"],
         summary="把某段文字定位到具体文件版本、页码和坐标",
         description=DESCRIPTIONS["source"], operation_id="get_block_source",
         response_model=SourceResponse, responses=error_responses(401, 404, 422),
         response_description="可核对的原文引用信息，含原件下载相对地址。")
def source(artifact_id: ArtifactPath, block_id: BlockPath, db: DB, user: CurrentUser):
    artifact, revision = artifact_access(db, artifact_id, user)
    block = db.get(DocumentBlock, (artifact_id, block_id))
    if block is None:
        raise HTTPException(404, "Block not found")
    return {"artifact_id": artifact.id, "revision_id": revision.id,
            "revision_sha256": revision.sha256, "block_id": block.block_id,
            "page": block.page, "bbox": block.bbox,
            "coordinate_system": "pdf_points_top_left", "quote": block.text,
            "text_hash": block.text_hash, "original_url": f"/api/v1/revisions/{revision.id}/original"}


@app.get("/api/v1/revisions/{revision_id}/original", tags=["05 来源追溯"], summary="预览或下载某个历史修订的原始 PDF",
         description=DESCRIPTIONS["original"], operation_id="download_original", response_class=FileResponse,
         responses={**error_responses(401, 404, 422, 503), 200: {
             "description": "原始 PDF 文件字节，不是 JSON；历史修订不会替换为最新文件。",
             "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
             "headers": {"Content-Disposition": {"description": "inline 便于预览；文件名为修订 ID 加 .pdf。", "schema": {"type": "string"}}}}})
def original(revision_id: RevisionPath, db: DB, user: CurrentUser):
    revision = db.get(DocumentRevision, revision_id)
    if revision is None:
        raise HTTPException(404, "Revision not found")
    document_access(db, revision.document_id, user)
    path = BlobStore(get_settings().storage_path).path(revision.storage_key)
    if not path.is_file():
        raise HTTPException(503, "Stored original is unavailable")
    return FileResponse(path, media_type="application/pdf", filename=f"{revision.id}.pdf",
                        content_disposition_type="inline")


app.include_router(business_router)
app.include_router(demo_router)
app.include_router(workbench_router)
app.include_router(quality_router)
app.include_router(extraction_router)
app.include_router(parse_router)
app.include_router(retrieval_router)
app.mount("/assets", StaticFiles(directory=FilePath(__file__).parent / "static"), name="frontend")


@app.get("/", include_in_schema=False)
def demo_home():
    return FileResponse(FilePath(__file__).parent / "static" / "index.html")


@app.get("/workspace", include_in_schema=False)
def workspace_home():
    return FileResponse(FilePath(__file__).parent / "static" / "workspace.html")


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    if request.url.path == "/api/v1/auth/session":
        # Pydantic's default error includes the rejected input; never echo a key.
        return JSONResponse(status_code=422, content={"detail": [
            {k: error[k] for k in ("type", "loc", "msg")} for error in exc.errors()]})
    return await request_validation_exception_handler(request, exc)
