"""解析质量检查与人工逐页核对；不改变人工业务审查结论。"""
import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import business as b, models as m, quality as q
from app.api_docs import error_responses
from app.business_schemas import NonBlank
from app.config import get_settings
from app.dependencies import CurrentUser, DB, WriteKey
from app.services import project_access
from app.storage import BlobStore, sha256

router = APIRouter(prefix="/api/v1/artifacts", tags=["12 解析质量核对"])
ArtifactID = Annotated[str, Path(description="成功解析后返回的产物 ID；质量记录绑定此不可变产物，不绑定文档最新版本。")]
Page = Annotated[int, Path(ge=1, description="PDF 实际页序，从1开始，必须位于该产物页数内。")]


class Finding(BaseModel):
    code: str = Field(description="可解释规则代码：NO_TEXT、SPARSE_TEXT、SUSPECT_ENCODING、INVALID_BBOX、OVERLAPPING_BLOCKS。")
    severity: Literal["INFO", "WARNING"] = Field(description="INFO 为低文字量提示；WARNING 建议优先回看原件，均不是确定错误。")
    message: str = Field(description="对该规则结果的中文解释。")
    suggestion: str = Field(description="建议的人工核对或重新处理方式。")
    affected_block_count: int = Field(description="触发规则的文字块数；无文字等页级规则为0。")
    block_ids: list[str] = Field(description="最多20个触发块 ID，可继续使用来源接口核对。")


class ReviewInput(NonBlank):
    expected_version: int = Field(ge=0, description="本页当前人工核对记录版本；未核对为0，防止覆盖别人意见。")
    expected_diagnostic_profile: str = Field(max_length=80, description="所见诊断规则版本，使用质量报告 diagnostic_profile；变化时返回409要求重看。")
    decision: Literal["TEXT_USABLE", "NEEDS_REPROCESS", "BLANK_CONFIRMED"] = Field(description="原件核对后认为文字可用、需要重新处理、或确认本页真实空白。空文字页不能标文字可用，有文字页不能标空白。")
    note: str = Field(min_length=1, max_length=4000, description="人工核对说明；写明原件是否有内容、文字是否有明显遗漏或需怎样处理。")


class ReviewResponse(BaseModel):
    id: str = Field(description="不可变人工核对记录 ID。")
    artifact_id: str = Field(description="核对的解析产物 ID。")
    page: int = Field(description="实际页序号。")
    version: int = Field(description="此产物此页内递增的核对记录版本。")
    diagnostic_profile: str = Field(description="操作时所见的诊断规则版本。")
    decision: str = Field(description="TEXT_USABLE、NEEDS_REPROCESS 或 BLANK_CONFIRMED；人工声明，不代表机器保证。")
    note: str = Field(description="核对说明，历史记录不会被覆盖。")
    reviewed_by: str = Field(description="实际操作用户 ID。")
    reviewer_name: str = Field(description="当前显示名，用于网页展示核对人。")
    created_at: datetime = Field(description="UTC 记录时间。")


class PageResult(BaseModel):
    page: int = Field(description="实际页序，从1开始。")
    width: float = Field(description="PDF 页面宽度，单位point。")
    height: float = Field(description="PDF 页面高度，单位point。")
    block_count: int = Field(description="本页冻结文字块数，不是业务要求数量。")
    character_count: int = Field(description="提取文字的非空白字符数，不能据此证明没有漏字。")
    findings: list[Finding] = Field(description="本页可解释规则提示，空列表只表示这些规则未命中。")
    latest_review: ReviewResponse | None = Field(description="此产物此页的最近人工核对；其他文件修订的记录不会继承。")


class QualityReport(BaseModel):
    artifact_id: str = Field(description="解析产物 ID。")
    revision_id: str = Field(description="原始不可变 PDF 修订 ID。")
    revision_sha256: str = Field(description="原始 PDF 摘要，用于识别来源。")
    artifact_sha256: str = Field(description="冻结解析 JSON 摘要；读取时验证完整性。")
    parser_profile: str = Field(description="原解析配置，不会因诊断重新编号或替换。")
    diagnostic_profile: str = Field(description="本次规则诊断版本，与解析配置独立。")
    original_url: str = Field(description="认证后打开对应原 PDF 的地址；可附加 #page=N 定位。")
    page_count: int = Field(description="总页数。")
    warning_page_count: int = Field(description="有 WARNING 规则提示的页数；即使人工确认空白也保留原提示。")
    reviewed_page_count: int = Field(description="有人工核对记录的页数，包含需要重处理的决定。")
    usable_page_count: int = Field(description="人工标文字可用或真实空白的页数。不是自动质量通过率。")
    needs_reprocess_page_count: int = Field(description="最新人工决定为需要重新处理的页数。")
    limitations: list[str] = Field(description="规则能力边界，任何人工核对都不改变当前无自动审查的事实。")
    pages: list[PageResult] = Field(description="按页序排列的指标、规则提示和最近人工记录。")


def access(db, artifact_id, user):
    artifact = db.get(m.ParseArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    revision = db.get(m.DocumentRevision, artifact.revision_id)
    document = db.get(m.Document, revision.document_id)
    project_access(db, document.project_id, user)
    return artifact, revision, document


def payload(artifact):
    try:
        data = BlobStore(get_settings().storage_path).read(artifact.storage_key)
        if sha256(data) != artifact.sha256:
            raise ValueError("hash")
        result = json.loads(data)
        if len(result["pages"]) != artifact.page_count or len(result["blocks"]) != artifact.block_count:
            raise ValueError("counts")
        return result
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "解析产物无法读取或完整性校验失败，请检查存储；不会用空结果冒充正常。")


def review_dto(db, row):
    return {**{k: getattr(row, k) for k in ("id", "artifact_id", "page", "version", "diagnostic_profile", "decision", "note", "reviewed_by", "created_at")},
            "reviewer_name": db.get(m.User, row.reviewed_by).name}


@router.get("/{artifact_id}/quality", operation_id="get_parse_quality", summary="按页查看解析质量提示和人工核对进度",
    response_model=QualityReport, responses=error_responses(401, 404, 422, 503),
    description="**业务场景**：上传 PDF 后，先检查用于整理要求和审查的原文是否明显缺失或乱码。任意项目成员可读。读取冻结解析 JSON 并验证摘要，再按页计算无文字、低文字量、疑似乱码、坐标异常和相邻块重叠提示，展示最近人工核对记录。不会重新解析、修改 block_id 或自动判定表格/阅读顺序正确。没有规则命中也不等于无漏字。下一步打开对应原件，记录页级人工判断；该记录不发布基线、不替代投标业务审查。")
def quality_report(artifact_id: ArtifactID, db: DB, user: CurrentUser, response: Response):
    artifact, revision, _ = access(db, artifact_id, user)
    pages = q.diagnose(payload(artifact))
    latest = {}
    for row in db.scalars(select(m.PageQualityReview).where(m.PageQualityReview.artifact_id == artifact_id)
                          .order_by(m.PageQualityReview.version.desc())):
        latest.setdefault(row.page, row)
    for page in pages:
        page["latest_review"] = review_dto(db, latest[page["page"]]) if page["page"] in latest else None
    decisions = [r.decision for r in latest.values()]
    response.headers["Cache-Control"] = "no-store"
    return {"artifact_id": artifact.id, "revision_id": revision.id, "revision_sha256": revision.sha256,
        "artifact_sha256": artifact.sha256, "parser_profile": artifact.parser_profile, "diagnostic_profile": q.PROFILE,
        "original_url": f"/api/v1/revisions/{revision.id}/original", "page_count": len(pages),
        "warning_page_count": sum(any(f["severity"] == "WARNING" for f in p["findings"]) for p in pages),
        "reviewed_page_count": len(latest), "usable_page_count": sum(v in {"TEXT_USABLE", "BLANK_CONFIRMED"} for v in decisions),
        "needs_reprocess_page_count": decisions.count("NEEDS_REPROCESS"), "limitations": q.LIMITATIONS, "pages": pages}


@router.post("/{artifact_id}/pages/{page}/quality-reviews", status_code=201, operation_id="review_parse_page",
    summary="回看原件后追加一条逐页质量核对记录", response_model=ReviewResponse,
    responses=error_responses(401, 403, 404, 409, 422, 503),
    description="**业务场景**：编写人或审查人回看某一页原 PDF，说明文字可用、需要重处理或真实空白。仅 OWNER/EDITOR/REVIEWER 可写，READER 只读。携带本页最近版本和所见规则版本，项目锁内复查权限并追加历史；并发意见变化返回409，幂等重试复用原结果。空文字页不能标文字可用，有提取文字的页不能直接确认为空白。新修订或新解析产物不继承旧核对，不改变业务 epoch、基线或最终审核结论；当前也不会自动启动 OCR。")
def review_page(artifact_id: ArtifactID, page: Page, body: ReviewInput, db: DB, user: CurrentUser, key: WriteKey):
    _, _, document = access(db, artifact_id, user)
    def append(db, project, actor, value):
        artifact = db.get(m.ParseArtifact, artifact_id)
        if not 1 <= page <= artifact.page_count:
            raise HTTPException(404, "PDF page not found")
        if value.expected_diagnostic_profile != q.PROFILE:
            raise HTTPException(409, "Diagnostic profile changed; reload quality report")
        last = db.scalar(select(m.PageQualityReview).where(m.PageQualityReview.artifact_id == artifact_id,
            m.PageQualityReview.page == page).order_by(m.PageQualityReview.version.desc()).limit(1))
        version = last.version if last else 0
        if value.expected_version != version:
            raise HTTPException(409, "Page review changed; reload quality report")
        has_text = bool(db.scalar(select(m.DocumentBlock.block_id).where(m.DocumentBlock.artifact_id == artifact_id,
            m.DocumentBlock.page == page).limit(1)))
        if value.decision == "TEXT_USABLE" and not has_text or value.decision == "BLANK_CONFIRMED" and has_text:
            raise HTTPException(409, "Decision conflicts with the extracted text; recheck the original page")
        payload(artifact)  # Do not acknowledge an unavailable/corrupted frozen result.
        row = m.PageQualityReview(project_id=project.id, artifact_id=artifact_id, page=page, version=version + 1,
            diagnostic_profile=q.PROFILE, decision=value.decision, note=value.note, reviewed_by=actor.id)
        db.add(row)
        db.flush()
        return review_dto(db, row)
    return b.mutate(db, user, document.project_id, key, body, f"REVIEW_PARSE_PAGE:{artifact_id}:{page}",
                    {"OWNER", "EDITOR", "REVIEWER"}, append)


@router.get("/{artifact_id}/pages/{page}/quality-reviews", operation_id="list_parse_page_reviews",
    summary="追溯一页历次人工质量核对意见", response_model=list[ReviewResponse], responses=error_responses(401, 404, 422),
    description="**业务场景**：同一页曾被标记需要处理，后来又被确认文字可用，需要知道谁在何时改变了判断。任意项目成员可读，返回该不可变解析产物该页的追加记录，按版本从新到旧，可分页。不会把别的文件修订或别的页的记录混入，也不删除早先意见。网页默认展示最近50条；需要更早记录时客户端可增加 offset。新文件的页码即使相同，也必须重新核对，不继承这里的历史决定。")
def history(artifact_id: ArtifactID, page: Page, db: DB, user: CurrentUser,
            offset: int = Query(default=0, ge=0, description="跳过的历史记录条数。"),
            limit: int = Query(default=50, ge=1, le=100, description="本次最多返回记录数，最大100。")):
    artifact, _, _ = access(db, artifact_id, user)
    if page > artifact.page_count:
        raise HTTPException(404, "PDF page not found")
    return [review_dto(db, r) for r in db.scalars(select(m.PageQualityReview).where(
        m.PageQualityReview.artifact_id == artifact_id, m.PageQualityReview.page == page)
        .order_by(m.PageQualityReview.version.desc()).offset(offset).limit(limit))]
