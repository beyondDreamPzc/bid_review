from datetime import date,datetime
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from app.business_schemas import SourceReference


class NoteInput(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    note: str=Field(min_length=5,max_length=2000,description="操作原因，至少5字符，保存到审计历史，不物理删除业务记录。")


class AssignmentInput(NoteInput):
    expected_version: int=Field(ge=1,description="当前任务version，版本变化409。")
    assignee_id: str=Field(description="本项目OWNER或EDITOR的用户ID。")
    due_date: date|None=Field(default=None,description="新整改期限，空表示取消期限；不会更改已有复核结论。")


class WithdrawInput(NoteInput):
    expected_version: int=Field(ge=1,description="问题对应的当前任务version。")
    withdrawn: bool=Field(description="true明确撤销误报/无效问题；false恢复并重新进入TODO。不能直接恢复退休要求的问题。")


class RetirementInput(NoteInput):
    expected_revision_no: int=Field(ge=1,description="当前要求的最新修订号。")
    retired: bool=Field(description="true退休、false恢复；须重新发布基线才改变冻结范围，未处理问题须先撤销。")


class ImpactInput(NoteInput):
    requirement_id: str=Field(description="受更正影响的有效逻辑要求ID。创建后该要求的旧判断失效，其他要求不因此改变。")
    sources: list[SourceReference]=Field(min_length=1,max_length=10,description="本项目AMENDMENT更正文件中的原文块，服务端冻结引用。")


class ImpactDecisionInput(NoteInput):
    expected_version: int=Field(ge=1,description="更正影响记录当前version。")
    disposition: Literal["REVISED","NO_CHANGE"]=Field(description="REVISED已依据该更正确认要求新修订；NO_CHANGE人工确认不改要求并说明原因。退休通过要求生命周期接口。")


class ImpactResponse(BaseModel):
    id: str=Field(description="更正影响记录ID。")
    requirement_id: str=Field(description="受影响逻辑要求。")
    source: list[dict]=Field(description="由服务器冻结的更正原文/页码/摘要。")
    note: str=Field(description="关联原因。")
    disposition: str=Field(description="PENDING、REVISED、NO_CHANGE或RETIRED。")
    version: int=Field(description="并发检查版本。")
    created_by: str=Field(description="登记人ID。")
    reviewed_by: str|None=Field(description="处理人ID，待处理为空。")
    review_note: str|None=Field(description="人工处理说明。")
    created_at: datetime=Field(description="UTC登记时间。")


class RetirementResponse(BaseModel):
    requirement_id: str=Field(description="逻辑要求ID。")
    retired: bool=Field(description="操作后的退休状态。")
    revision_no: int=Field(description="未变的最后修订号。")


class RemovedMember(BaseModel):
    user_id: str=Field(description="被移除用户ID。")
    removed: bool=Field(description="true表示项目访问已撤销；历史署名仍保留。")


class PageResponse(BaseModel):
    items: list[dict]=Field(description="权限范围内的本页数据；不同资源字段见对应业务接口。")
    total: int=Field(description="筛选后的记录数。")
    offset: int=Field(description="从0开始的偏移。")
    limit: int=Field(description="本页上限，最大100。")
