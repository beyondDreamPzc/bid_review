"""Human evidence discovery only; a relevance score is never a compliance decision."""
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from app import business as b, models as m, retrieval as r
from app.api_docs import error_responses
from app.config import get_settings
from app.dependencies import CurrentUser, DB, WriteKey
from app.milvus import RetrievalUnavailable

router = APIRouter(prefix="/api/v1/projects/{project_id}/retrieval", tags=["14 正式材料检索"])
ProjectId = Annotated[str, Path(description="要查询的项目ID。每次操作重新检查项目成员权限。")]


class IndexInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_material_set_id: str = Field(min_length=36, max_length=36, description="页面上已发布的正式材料集ID；与当前不一致返回409，防止误建旧版本。")
    retry_failed: bool = Field(default=False, description="明确重试失败任务。活动任务始终复用，不重复入队。")
    rebuild: bool = Field(default=False, description="明确重建成功索引，例如Milvus数据丢失。重建完成前本轮检索不可用，保留来源快照。")


class IndexResponse(BaseModel):
    id: str = Field(description="MySQL冻结索引记录ID，绑定一个正式材料集及一个检索配置。")
    job_id: str = Field(description="后台构建任务ID，通过后台任务接口查看状态；202不代表可以检索。")
    reused: bool = Field(description="是否复用已存在的本轮索引任务。")


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_material_set_id: str = Field(min_length=36, max_length=36, description="当前页面采用的正式材料集ID；查询前后都检查，版本变化则409。")
    query: str = Field(min_length=1, max_length=500, description="待定位的关键词或条款，例如“故障响应时限”；采用中文分词BM25召回，不是模型问答。")
    limit: int = Field(default=5, ge=1, le=10, description="最多返回多少个不同原文块。无匹配返回空数组，不编造答案。")


class Source(BaseModel):
    artifact_id: str = Field(description="冻结解析产物ID。与block_id一起可用于现有证据选择接口。")
    artifact_sha256: str = Field(description="冻结解析JSON摘要。")
    block_id: str = Field(description="产物内的原始文字块ID，可能包含多个检索片段。")
    revision_id: str = Field(description="对应不可变PDF修订ID。")
    revision_sha256: str = Field(description="原始PDF的SHA256摘要。")
    document_id: str = Field(description="逻辑文档ID。")
    title: str = Field(description="索引构建时冻结的文档名称。")
    parser_profile: str = Field(description="材料采用的解析配置，重解析不会自动替换。")
    page: int = Field(description="原PDF实际页码，从1开始。")
    bbox: list[float] = Field(description="整个原文块的PDF点矩形，左上角原点；不是片段或词语的精确坐标。")
    text_hash: str = Field(description="整个原文块的UTF8文本摘要。")
    submission_role: str = Field(description="FORMAL_RESPONSE正式响应或FORMAL_ATTACHMENT正式附件；排除REFERENCE。")
    start: int = Field(description="片段在原文块中的Python字符起始位置，从0开始；不是字节位置。")
    end: int = Field(description="片段在原文块中的字符结束位置，不包含该位置。")


class Hit(BaseModel):
    chunk_id: str = Field(description="MySQL不可变片段ID。结果正文从MySQL取回并校验，不相信外部索引中的正文。")
    score: float = Field(description="BM25相关性排序分数，不是概率、置信度或满足要求的结论。")
    quote: str = Field(description="未改写的原文片段，最多1200字符。数字、条件和措辞均保留。")
    source: Source
    original_url: str = Field(description="经过权限检查的原件接口地址，带PDF实际页码定位片段。")


class SearchResponse(BaseModel):
    material_set_id: str = Field(description="本次实际检索的正式材料集。")
    index_id: str = Field(description="完整构建后发布的索引快照ID。")
    profile: str = Field(description="冻结的分块、分词和稀疏检索算法配置。")
    query: str = Field(description="去掉首尾空白后的查询。")
    results: list[Hit] = Field(description="按相关性排列、按原文块去重的结果。空数组表示没有召回，不能据此认定响应缺失。")


class StatusResponse(BaseModel):
    enabled: bool = Field(description="当前安装是否启用检索。")
    material_set_id: str | None = Field(description="当前正式材料集ID，尚未发布时为空。")
    material_version: int | None = Field(description="当前正式材料集的业务版本号。")
    profile: str = Field(description="当前检索配置。")
    index_id: str | None = Field(description="本轮索引ID；尚未创建为空。")
    job_id: str | None = Field(description="本轮构建任务ID。")
    status: str = Field(description="DISABLED、NOT_BUILT，或任务QUEUED/RUNNING/RETRY_WAIT/SUCCEEDED/FAILED。")
    chunk_count: int = Field(description="本轮冻结的片段数量，不能代表文字完整性。")
    error_detail: str | None = Field(description="安全的错误提示，不包含文档内容或连接密钥。")


def enabled():
    settings = get_settings()
    if not settings.retrieval_enabled:
        raise HTTPException(503, "本安装尚未启用正式材料检索。")
    return settings


@router.get("", response_model=StatusResponse, operation_id="material_retrieval_status",
    summary="查看当前正式材料集的索引状态", responses=error_responses(401,404),
    description="**业务场景**：进入证据检索页面时，明确当前搜的是第几套正式材料、是否已建好索引。所有项目成员可读。该接口只读取MySQL任务事实，不探测Milvus健康；成功构建后的服务故障会在实际查询时报告503。")
def status(project_id: ProjectId, db: DB, user: CurrentUser):
    project, _ = b.access(db, project_id, user)
    index = r.current_index(db, project)
    job = db.get(m.Job, index.job_id) if index else None
    material = db.get(m.MaterialSet, project.current_material_set_id) if project.current_material_set_id else None
    return {"enabled": get_settings().retrieval_enabled, "material_set_id": project.current_material_set_id,
        "material_version": material.version if material else None, "profile": r.PROFILE,
        "index_id": index.id if index else None, "job_id": job.id if job else None,
        "status": "DISABLED" if not get_settings().retrieval_enabled else job.status if job else "NOT_BUILT",
        "chunk_count": index.chunk_count if index else 0, "error_detail": job.error_detail if job else None}


@router.post("/indexes", status_code=202, response_model=IndexResponse,
    operation_id="build_material_index", summary="为当前正式材料构建可追溯检索索引",
    responses=error_responses(401,403,404,409,422,503),
    description="**业务场景**：负责人选定正式响应与附件后，让团队能搜索本轮响应证据。仅OWNER/EDITOR；必须带幂等键。项目行锁下冻结文档/修订/解析配置/原文块，最多10000片段；每块按1200字符、120字符重叠切分，绝不跨页或跨块拼接。排除仅供参考材料。后台异步写Milvus，全部完成且租约有效才发布检索代次；相同材料和配置复用任务，可明确失败重试或成功重建。材料变更后不会沿用旧索引。")
def build(project_id: ProjectId, body: IndexInput, db: DB, user: CurrentUser, key: WriteKey):
    enabled()
    return b.mutate(db, user, project_id, key, body, "BUILD_MATERIAL_INDEX", b.EDIT, r.enqueue)


@router.post("/search", response_model=SearchResponse, operation_id="search_material_evidence",
    summary="查找当前正式材料里的原文证据", responses=error_responses(401,404,409,422,503),
    description="**业务场景**：核对“2小时响应”等要求时，定位响应书承诺在哪一页。所有项目成员可查询，正文不发送云模型。Milvus中文分词与BM25稀疏向量检索；服务端强制项目及已发布代次过滤，返回结果再从MySQL按片段ID取回并校验原文。查询期间换材料、重建索引或移除成员时拒绝返回旧结果。分数仅表示相关性，最终是否满足要求由人工判断；无命中不等于未响应。此查询不修改业务状态，无需幂等键。")
def search(project_id: ProjectId, body: SearchInput, db: DB, user: CurrentUser):
    settings = enabled()
    try:
        return r.search(db, user, project_id, body, settings)
    except RetrievalUnavailable as error:
        raise HTTPException(503, str(error)) from None
