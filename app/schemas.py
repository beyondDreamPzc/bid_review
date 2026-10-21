"""公开接口契约：字段说明直接展示在 Swagger 的 Schema 中。"""
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

PROJECT_ID = "11111111-1111-4111-8111-111111111111"
DOCUMENT_ID = "22222222-2222-4222-8222-222222222222"
REVISION_ID = "33333333-3333-4333-8333-333333333333"
JOB_ID = "44444444-4444-4444-8444-444444444444"
ARTIFACT_ID = "55555555-5555-4555-8555-555555555555"
HASH = "e62549d0c0326992b008c73ebdc6e14934e485b1adbdd6a1a79aee3ab9f5c4f6"

BBox = Annotated[list[float], Field(
    min_length=4, max_length=4,
    description="文字在该 PDF 页上的矩形位置：[左、上、右、下]。单位为 PDF point（1/72 英寸），原点在页面左上角；不是屏幕像素，前端缩放时需要换算。",
    examples=[[79.4, 159.783, 523.025, 170.283]],
)]


class ErrorResponse(BaseModel):
    """HTTP 错误；字段校验错误的 detail 是数组，其余业务错误一般为字符串。"""
    detail: str | list[dict[str, Any]] = Field(
        description="错误详情。字符串说明业务错误；数组中的 loc 表示出错位置，例如 ['header', 'idempotency-key']，msg 表示原因。",
        examples=["Project not found"],
    )


class LiveResponse(BaseModel):
    status: Literal["ok"] = Field(description="ok：API 进程能够响应 HTTP 请求。", examples=["ok"])


class ReadyResponse(BaseModel):
    status: Literal["ready"] = Field(description="ready：数据库可连接且核心业务表可查询。", examples=["ready"])
    stage: str = Field(description="当前阶段 human-review-workflow：文档工程和人工审查闭环。", examples=["human-review-workflow"])
    formal_review_ready: Literal[False] = Field(description="当前固定为 false：尚未开放自动模型审查；人工业务已可用。这与数据库是否就绪无关。", examples=[False])


class ProjectInput(BaseModel):
    name: str = Field(title="项目名称", min_length=1, max_length=200,
                      description="本次投标工作的名称，建议写采购项目名称。首尾空格会去掉；纯空白名称会返回 422。",
                      examples=["上海12345平台二期投标材料检查"])


class ProjectResponse(BaseModel):
    id: str = Field(description="项目 ID。上传文档时填入路径参数 project_id。", examples=[PROJECT_ID])
    name: str = Field(description="项目名称。", examples=["上海12345平台二期投标材料检查"])


class UploadResponse(BaseModel):
    document_id: str = Field(description="逻辑文档 ID。一份文档的多个修订共用此 ID；上传新修订时使用它。", examples=[DOCUMENT_ID])
    revision_id: str = Field(description="本次文件的不可变修订 ID。下载原件时使用它。", examples=[REVISION_ID])
    revision_no: int = Field(description="同一逻辑文档内从 1 开始递增的修订号。它不是项目的总文档数。", ge=1, examples=[1])
    job_id: str = Field(description="后台文字层解析任务 ID。用 GET /api/v1/jobs/{job_id} 查询处理状态。", examples=[JOB_ID])
    sha256: str = Field(description="上传原始 PDF 字节的 SHA-256，用于验证原件一致性；不是文字内容摘要。", examples=[HASH])
    reused: bool = Field(description="true：上传新修订时发现同一文档已有完全相同的文件，复用旧修订和任务。幂等键重放返回原响应，reused 也保持原值，因此 false 不代表这次一定新增记录。", examples=[False])


class RevisionResponse(BaseModel):
    id: str = Field(description="不可变修订 ID，可作为下载原件接口的 revision_id。", examples=[REVISION_ID])
    revision_no: int = Field(description="文档内修订号，按此字段升序返回。", examples=[1])
    sha256: str = Field(description="该修订原始 PDF 字节的 SHA-256。", examples=[HASH])
    status: str = Field(description="文件处理状态：UPLOADED 已接收；PARSING 处理中；NEEDS_REVIEW 已完成文字层探针但待检查；RETRY_WAIT 等待重试；PARSE_FAILED 处理失败。", examples=["NEEDS_REVIEW"])
    created_at: datetime = Field(description="修订登记时间，使用 UTC。当前返回值不带时区后缀，请按 UTC 解释；北京时间需加 8 小时。", examples=["2026-10-19T08:19:43"])


class JobResponse(BaseModel):
    id: str = Field(description="执行任务 ID，对应上传或要求抽取接口返回的 job_id。", examples=[JOB_ID])
    status: str = Field(description="QUEUED 排队；RUNNING 处理中；RETRY_WAIT 等待自动重试；SUCCEEDED 本次技术处理完成；FAILED 最终失败；CANCELLED 抽取任务已取消。SUCCEEDED 不表示投标满足要求。", examples=["SUCCEEDED"])
    attempt: int = Field(description="Worker 实际领取任务的次数。排队尚未执行时为 0，首次执行为 1；不是当前进度百分比。", ge=0, examples=[1])
    artifact_id: str | None = Field(description="PDF解析成功后的产物 ID；要求抽取任务使用专门的 extraction-runs 接口查看候选，此字段可以为空。", examples=[ARTIFACT_ID])
    error_code: str | None = Field(description="最近错误代码：PDF_REJECTED 文件不可处理；PROCESSING_ERROR 解析异常；LEASE_EXPIRED 租约过期；MODEL_* 或 EXTRACTION_* 表示候选抽取错误，具体看抽取任务接口。无错误或成功后为 null。", examples=[None])
    error_detail: str | None = Field(description="可用于定位失败原因的简短信息。不会返回完整文档、密钥或服务器存储路径。", examples=[None])
    formal_review_ready: Literal[False] = Field(description="当前固定为 false：解析只提取文字层，模型只建议要求候选，均不具备自动审查能力；人工引用时须核对原件。", examples=[False])


class ArtifactResponse(BaseModel):
    id: str = Field(description="解析产物 ID。一个产物代表某个文件修订使用某套解析配置生成的结果。", examples=[ARTIFACT_ID])
    revision_id: str = Field(description="该产物来源的不可变文件修订 ID。", examples=[REVISION_ID])
    revision_sha256: str = Field(description="来源 PDF 原始字节的 SHA-256，可用于核对引用版本。", examples=[HASH])
    parser_profile: str = Field(description="解析配置版本。当前 pdfplumber-probe-v1 只提取文字层及坐标，不验证表格语义或扫描件 OCR。", examples=["pdfplumber-probe-v1"])
    page_count: int = Field(description="原 PDF 的实际页数，包含无文字层页面。", ge=0, examples=[65])
    block_count: int = Field(description="生成的文字来源块总数。当前通常一行文字为一个块；不是要求数量或 RAG chunk 数量。", ge=0, examples=[1806])
    quality_status: str = Field(description="当前固定为 NEEDS_REVIEW，表示需要检查解析质量，不是人工审查已通过。", examples=["NEEDS_REVIEW"])
    quality_flags: list[str] = Field(description="质量提示代码。PROVISIONAL_TEXT_LAYER_ONLY 仅文字层；TABLE_STRUCTURE_NOT_VALIDATED 表格未验证；OCR_NOT_PERFORMED 未做 OCR；NO_EXTRACTABLE_TEXT 没有可提取文字；PAGES_NEED_ATTENTION 有页面需人工检查。", examples=[["PROVISIONAL_TEXT_LAYER_ONLY", "TABLE_STRUCTURE_NOT_VALIDATED", "OCR_NOT_PERFORMED"]])
    formal_review_ready: Literal[False] = Field(description="当前固定为 false；产物存在不代表自动模型可判断投标满足，人工仍需核对原件。", examples=[False])


class BlockResponse(BaseModel):
    block_id: str = Field(description="当前产物内的块 ID，例如 p0003-b0004 为第 3 页第 4 个文字块。只能与本 artifact_id 配合使用。", examples=["p0003-b0004"])
    page: int = Field(description="PDF 实际页序号，从 1 开始；可能与页面印刷的页码不相同。", ge=1, examples=[3])
    bbox: BBox
    text: str = Field(description="提取出的该行原文。用于阅读及来源验证，不是模型生成的回答。", examples=["测试示例：投标文件应在约定截止时间前提交。"])
    text_hash: str = Field(description="该块 text 按 UTF-8 编码计算的 SHA-256，用于检查文字是否改变。", examples=["a" * 64])


class SourceResponse(BaseModel):
    artifact_id: str = Field(description="该来源块所属的解析产物 ID。", examples=[ARTIFACT_ID])
    revision_id: str = Field(description="该块对应的不可变原文件修订 ID。", examples=[REVISION_ID])
    revision_sha256: str = Field(description="原文件 SHA-256，用于确保引用和下载原件属于同一版本。", examples=[HASH])
    block_id: str = Field(description="产物内部的来源块 ID。", examples=["p0003-b0004"])
    page: int = Field(description="PDF 实际页序号，从 1 开始。", ge=1, examples=[3])
    bbox: BBox
    coordinate_system: Literal["pdf_points_top_left"] = Field(description="坐标系名称：PDF point 为单位，页面左上角为原点。", examples=["pdf_points_top_left"])
    quote: str = Field(description="该来源块的完整提取原文，与文字块列表的 text 对应。", examples=["测试示例：投标文件应在约定截止时间前提交。"])
    text_hash: str = Field(description="quote 的 UTF-8 SHA-256，与同一块的 text_hash 相同。", examples=["a" * 64])
    original_url: str = Field(description="下载这个修订原 PDF 的相对接口地址。需有效浏览器登录 Cookie 或 X-API-Key 认证。", examples=[f"/api/v1/revisions/{REVISION_ID}/original"])
