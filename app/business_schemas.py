"""人工审查业务的公开数据契约；来源与版本必须明确。"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas import BBox


class SourceReference(BaseModel):
    artifact_id: str = Field(description="解析产物 ID，必须属于当前项目和对应的招标/响应快照。")
    block_id: str = Field(description="该产物中的文字块 ID；服务端会回查原文，不能由客户端自造引文。")


class EvidenceSnapshot(SourceReference):
    revision_id: str = Field(description="来源文件的不可变修订 ID。")
    document_id: str = Field(description="逻辑文档 ID。")
    document_kind: str = Field(description="来源类型：TENDER/AMENDMENT/RESPONSE/EVIDENCE。")
    revision_sha256: str = Field(description="原文件字节的 SHA-256。")
    page: int = Field(description="PDF 实际页序，从 1 开始。")
    bbox: BBox = Field(description="原文在该页的矩形框 [x0, top, x1, bottom]，单位 PDF point，左上角为原点。")
    quote: str = Field(description="服务端从来源块复制的原文。")
    text_hash: str = Field(description="原文 UTF-8 SHA-256。")
    submission_role: str | None = Field(default=None, description="响应证据的角色：FORMAL_RESPONSE/FORMAL_ATTACHMENT/REFERENCE；要求来源为 null。")


class NonBlank(BaseModel):
    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def reject_blank_text(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("Text fields must not be blank")
        return value.strip() if isinstance(value, str) else value


class MemberInput(NonBlank):
    user_id: str = Field(description="已在系统中创建的用户 ID。用户可通过 /api/v1/me 查询自己的 ID。")
    role: Literal["EDITOR", "REVIEWER", "READER"] = Field(description="EDITOR 编写/整改；REVIEWER 确认要求、登记问题和复核；READER 只读。只有项目 OWNER 可设置。")


class MemberResponse(BaseModel):
    user_id: str = Field(description="用户 ID。")
    name: str = Field(description="用户显示名。")
    role: str = Field(description="项目角色：OWNER/EDITOR/REVIEWER/READER。")


class MeResponse(BaseModel):
    id: str = Field(description="当前 API Key 或浏览器会话对应的用户 ID，不返回密钥或 hash。")
    name: str = Field(description="当前用户显示名称。")


class RequirementInput(NonBlank):
    title: str = Field(min_length=1, max_length=200, description="要求标题，例如故障响应时限。", examples=["故障响应时限"])
    text: str = Field(min_length=1, max_length=8000, description="可单独核对的一项招标要求，保持原意。", examples=["故障响应时间不得超过2小时。"])
    category: Literal["TECHNICAL", "QUALIFICATION", "DELIVERY", "FORMAT", "OTHER"] = Field(description="要求类别：技术、资质、交付、格式或其他。")
    priority: Literal["MANDATORY", "SCORING", "GENERAL"] = Field(description="重要性，须按招标文件定义人工确认，不能仅凭符号猜测。")
    sources: list[SourceReference] = Field(min_length=1, max_length=20, description="至少一个本项目招标/更正文件的原文位置；服务端保存完整来源快照。")


class RequirementRevisionInput(RequirementInput):
    expected_revision_no: int = Field(ge=1, description="当前最新修订号。与数据库不一致返回 409，防止覆盖其他人的修改。")


class ConfirmRequirementInput(BaseModel):
    expected_revision_no: int = Field(ge=1, description="本次确认的最新要求修订号；只能确认当前最新草稿。")


class RequirementResponse(BaseModel):
    requirement_id: str = Field(description="逻辑要求 ID。")
    revision_id: str = Field(description="该要求不可变修订 ID。正文修改会创建新 ID。")
    revision_no: int = Field(description="该逻辑要求内递增的修订号。")
    title: str = Field(description="要求标题。")
    text: str = Field(description="本修订的完整要求正文。")
    category: str = Field(description="要求类别。")
    priority: str = Field(description="人工标定的重要性。")
    status: str = Field(description="DRAFT 待确认；CONFIRMED 已确认可纳入基线。确认不等于投标响应满足。")
    sources: list[EvidenceSnapshot] = Field(description="要求出处的不可变引用快照。")
    created_by: str = Field(description="创建本修订的用户 ID。")
    confirmed_by: str | None = Field(description="确认人 ID；草稿为 null。")
    created_at: datetime = Field(description="UTC 创建时间，当前无时区后缀。")


class BaselineInput(NonBlank):
    name: str = Field(default="要求基线", max_length=200, description="基线名称，例如首次确认版。")
    expected_epoch: int = Field(ge=0, description="工作台当前 review_epoch；版本变化后须刷新。")
    expected_current_baseline_id: str | None = Field(default=None, description="预期上一基线 ID；首次发布为 null。")
    requirement_revision_ids: list[str] = Field(min_length=1, max_length=1000, description="当前全部要求的最新已确认修订 ID，不能遗漏、重复或包含草稿。")


class BaselineResponse(BaseModel):
    id: str = Field(description="发布后的不可变基线 ID。")
    project_id: str = Field(description="所属项目 ID。")
    version: int = Field(description="项目内基线版本号。")
    name: str = Field(description="基线名称。")
    parent_id: str | None = Field(description="上一基线 ID，首版为 null。")
    requirements: list[RequirementResponse] = Field(description="基线冻结的全部要求修订及来源。")
    created_by: str = Field(description="发布人 ID。")
    created_at: datetime = Field(description="UTC 发布时间。")


class MaterialSelection(BaseModel):
    artifact_id: str = Field(description="选定 PDF 修订的解析产物 ID，必须是本项目的响应/证明材料。")
    submission_role: Literal["FORMAL_RESPONSE", "FORMAL_ATTACHMENT", "REFERENCE"] = Field(description="正式响应、正式附件、仅供参考。仅参考不能证明本次正式提交已满足。")


class MaterialSnapshot(MaterialSelection):
    revision_id: str = Field(description="选定的不可变文件修订 ID。")
    document_id: str = Field(description="逻辑文档 ID，同一材料集不能混入其多个版本。")
    title: str = Field(description="文档名称。")
    document_kind: str = Field(description="RESPONSE 或 EVIDENCE。")
    sha256: str = Field(description="原文件 hash。")
    parser_profile: str = Field(description="冻结的解析配置版本；MinerU与历史探针产物可共存，均需人工核对。")


class MaterialSetInput(NonBlank):
    name: str = Field(default="正式响应材料", max_length=200, description="本套材料的名称。")
    expected_epoch: int = Field(ge=0, description="工作台当前 review_epoch。")
    expected_current_material_set_id: str | None = Field(default=None, description="预期当前材料集 ID；首次为 null。")
    items: list[MaterialSelection] = Field(min_length=1, max_length=200, description="显式选择文件和角色；至少一份 FORMAL_RESPONSE，不能自动选最后上传的文件。")


class MaterialSetResponse(BaseModel):
    id: str = Field(description="不可变材料集 ID。")
    project_id: str = Field(description="项目 ID。")
    version: int = Field(description="项目内材料集版本号。")
    name: str = Field(description="材料集名称。")
    items: list[MaterialSnapshot] = Field(description="冻结的文件修订、解析配置和提交角色。")
    created_by: str = Field(description="发布人 ID。")
    created_at: datetime = Field(description="UTC 发布时间。")


class IssueInput(NonBlank):
    expected_epoch: int = Field(ge=0, description="当前工作台 epoch，保证问题登记在所见的基线和材料版本上。")
    requirement_revision_id: str = Field(description="当前基线中的要求修订 ID。")
    title: str = Field(min_length=1, max_length=200, description="问题标题。", examples=["响应时限与招标要求冲突"])
    description: str = Field(min_length=1, max_length=8000, description="人工核对依据，例如要求2小时而响应为4小时。")
    kind: Literal["CONFLICT", "MISSING_RESPONSE", "MISSING_EVIDENCE", "OTHER"] = Field(description="冲突、缺少响应、缺少证明或其他。")
    severity: Literal["HIGH", "MEDIUM", "LOW"] = Field(description="人工标记的问题优先级。")
    assignee_id: str = Field(description="整改负责人 ID，必须是本项目 OWNER 或 EDITOR。")
    due_date: date | None = Field(default=None, description="可选整改期限，格式 YYYY-MM-DD。")
    evidence: list[SourceReference] = Field(default_factory=list, max_length=20, description="响应证据。CONFLICT 必须附至少一处正式材料原文；缺失问题可为空并在描述中说明核对范围。")


class TaskTransitionInput(BaseModel):
    action: Literal["START", "SUBMIT"] = Field(description="START 领取开始/退回后重做；SUBMIT 提交整改。只允许任务负责人操作。")
    expected_version: int = Field(ge=1, description="任务当前 version，防止并发重复状态变更。")
    expected_epoch: int = Field(ge=0, description="工作台当前 review_epoch；材料或要求基线变化后必须刷新核对再操作。")
    note: str = Field(default="", max_length=8000, description="SUBMIT 必须说明修改内容；START 可省略。")
    evidence: list[SourceReference] = Field(default_factory=list, max_length=20, description="SUBMIT 必须引用当前正式材料集中的修改后原文，不能引用仅参考材料。")


class TaskDecisionInput(NonBlank):
    expected_version: int = Field(ge=1, description="当前任务 version。")
    submission_id: str = Field(description="本次复核的 current_submission.id，不能误验收旧提交。")
    decision: Literal["ACCEPT", "RETURN"] = Field(description="ACCEPT 验收；RETURN 退回。只允许 OWNER/REVIEWER，且不能验收或退回自己提交的整改。")
    note: str = Field(min_length=1, max_length=8000, description="复核意见，无论通过或退回都必须填写。")


class SubmissionResponse(BaseModel):
    id: str = Field(description="不可变整改提交 ID。")
    task_version: int = Field(description="提交时的任务版本。")
    requirement_revision_id: str = Field(description="本次整改依据的当前要求修订。")
    baseline_id: str = Field(description="提交时要求基线。")
    material_set_id: str = Field(description="提交时正式材料集。")
    epoch: int = Field(description="提交时 review_epoch。输入变化后此提交需要重新确认。")
    note: str = Field(description="整改说明。")
    evidence: list[EvidenceSnapshot] = Field(description="修改后正式材料的引用。")
    submitted_by: str = Field(description="实际提交人 ID。")
    created_at: datetime = Field(description="UTC 提交时间。")


class TaskDecisionResponse(BaseModel):
    id: str = Field(description="不可变复核记录 ID。")
    submission_id: str = Field(description="复核的整改提交 ID。")
    decision: str = Field(description="ACCEPT 或 RETURN。")
    note: str = Field(description="复核意见。")
    decided_by: str = Field(description="复核人 ID。")
    task_version: int = Field(description="该复核操作完成后的任务版本。")
    created_at: datetime = Field(description="UTC 复核时间。")


class TaskResponse(BaseModel):
    id: str = Field(description="整改任务 ID。")
    issue_id: str = Field(description="对应的审查问题 ID。")
    requirement_id: str = Field(description="逻辑要求 ID，新修订仍沿用此关系。")
    assignee_id: str = Field(description="整改负责人。")
    due_date: date | None = Field(description="整改期限。")
    status: str = Field(description="持久化状态：TODO/IN_PROGRESS/SUBMITTED/ACCEPTED/RETURNED。")
    effective_status: str = Field(description="当前业务状态；已提交或已验收的结果遇到输入版本变化时为 NEEDS_RECHECK，历史状态保留。")
    freshness: str = Field(description="CURRENT 或 STALE，相对于项目当前基线、材料集与 epoch。")
    version: int = Field(description="乐观锁版本，执行下一个动作时作为 expected_version。")
    current_submission: SubmissionResponse | None = Field(description="最近一次整改提交；尚未提交为 null。")
    decisions: list[TaskDecisionResponse] = Field(description="此任务全部人工复核记录，按任务版本递增。")


class IssueResponse(BaseModel):
    id: str = Field(description="人工登记的问题 ID。")
    requirement_id: str = Field(description="问题对应的逻辑要求。")
    requirement_revision_id: str = Field(description="登记问题时的要求修订，历史不覆盖。")
    baseline_id: str = Field(description="登记问题时的基线。")
    material_set_id: str = Field(description="登记问题时的材料集。")
    epoch: int = Field(description="登记时 epoch。")
    title: str = Field(description="问题标题。")
    description: str = Field(description="人工核对的依据和缺口。")
    kind: str = Field(description="问题类型。")
    severity: str = Field(description="问题优先级。")
    evidence: list[EvidenceSnapshot] = Field(description="登记时响应材料的来源。")
    status: str = Field(description="OPEN 待整改；RESOLVED 当前版本已复核验收；NEEDS_RECHECK 旧验收已过期。")
    freshness: str = Field(description="原始问题是否仍是当前输入；旧问题历史可为 STALE，但整改可在新版本完成。")
    task: TaskResponse = Field(description="对应的整改任务，一条问题只建一条任务，补件后继续使用。")


class RequirementDecisionInput(NonBlank):
    expected_epoch: int = Field(ge=0, description="项目当前 epoch。")
    requirement_revision_id: str = Field(description="当前基线内的要求修订。")
    decision: Literal["CONFIRMED_SATISFIED", "CONFIRMED_ISSUE", "NOT_APPLICABLE"] = Field(description="人工确认满足、确认有问题、确认不适用。不是模型自动结论。")
    note: str = Field(min_length=1, max_length=8000, description="人工审核意见；不适用必须说明原因。")
    evidence: list[SourceReference] = Field(default_factory=list, max_length=20, description="确认满足必须提供正式材料引用；其他决定可按实际情况提供。")


class RequirementDecisionResponse(BaseModel):
    id: str = Field(description="不可变人工审核记录 ID。")
    requirement_id: str = Field(description="逻辑要求 ID。")
    requirement_revision_id: str = Field(description="审核的具体要求修订。")
    baseline_id: str = Field(description="对应基线。")
    material_set_id: str = Field(description="对应正式材料集。")
    epoch: int = Field(description="决定适用的项目输入版本。")
    sequence: int = Field(description="该逻辑要求内递增的决定序号，不能靠同秒时间排序。")
    review_version: int = Field(description="该要求的问题代次；新增问题会递增，之前的满足决定必须重新确认。")
    decision: str = Field(description="人工确认满足/有问题/不适用。")
    note: str = Field(description="审核意见。")
    evidence: list[EvidenceSnapshot] = Field(description="审核依据的正式材料引用。")
    decided_by: str = Field(description="审核人 ID。")
    created_at: datetime = Field(description="UTC 审核时间。")


class WorkspaceResponse(BaseModel):
    project_id: str = Field(description="投标项目 ID。")
    name: str = Field(description="项目名称。")
    my_role: str = Field(description="当前用户的项目角色。")
    review_epoch: int = Field(description="当前有效业务输入版本。发布要求基线/材料集会递增，写操作须携带所见值。")
    current_baseline_id: str | None = Field(description="当前要求基线；尚未发布为 null。")
    current_material_set_id: str | None = Field(description="当前正式材料集；尚未发布为 null。")
    requirement_count: int = Field(description="已录入逻辑要求数。")
    issue_count: int = Field(description="历史登记的问题总数，不等于当前未解决数。")
    pending_requirement_changes: bool = Field(description="存在未纳入当前基线的新要求/新修订；需确认并重新发布基线。")
    review_mode: Literal["HUMAN"] = Field(description="最终判断仍由人工完成；可选模型仅建议要求候选，不自动确认要求或审查响应。")


class RequirementReportRow(BaseModel):
    requirement_id: str = Field(description="基线内逻辑要求 ID。")
    requirement_revision_id: str = Field(description="基线冻结的修订 ID。")
    title: str = Field(description="要求标题。")
    status: str = Field(description="UNREVIEWED 未有当前结论；ISSUES_OPEN 有未解决问题；NEEDS_REVIEW 问题处理后仍待最终确认；REVIEWED 已人工完成。")
    unresolved_issue_count: int = Field(description="该逻辑要求尚未在当前输入下解决的问题数。")
    current_decision: RequirementDecisionResponse | None = Field(description="当前基线/材料/epoch 的最新人工决定；旧决定不冒充当前。")


class ReviewReportResponse(BaseModel):
    project_id: str = Field(description="项目 ID。")
    baseline_id: str | None = Field(description="报告对应的当前基线。")
    material_set_id: str | None = Field(description="报告对应的当前材料集。")
    review_epoch: int = Field(description="报告读取的业务输入 epoch。")
    review_mode: Literal["HUMAN"] = Field(description="人工审查，不包含自动 RAG/模型判断。")
    status: str = Field(description="NOT_READY 缺基线/材料；ISSUES_OPEN 有未解决问题；IN_REVIEW 尚有要求未确认；REVIEW_COMPLETE 本快照的人工审查已完成。")
    manual_review_complete: bool = Field(description="只有全部要求有当前人工确认且没有未解决问题时为 true；没有问题记录不等于审查完成。")
    pending_requirement_changes: bool = Field(description="有尚未纳入基线的要求修改时为 true，阻止项目显示人工审查完成。")
    requirement_count: int = Field(description="当前基线的要求数。")
    reviewed_count: int = Field(description="已在当前输入下人工确认满足/不适用且无未解决问题的要求数。")
    unresolved_issue_count: int = Field(description="当前基线逻辑要求关联的未解决问题数，包含需重审的旧验收。")
    requirements: list[RequirementReportRow] = Field(description="逐项人工审查覆盖和问题状态。")
