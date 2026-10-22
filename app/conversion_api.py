from typing import Annotated as PathAnnotated
from fastapi import Path as APIPath
from typing import Annotated,Literal
from fastapi import APIRouter,File,Form,UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from sqlalchemy import select
from app import business as b,models as m
from app.config import get_settings
from app.dependencies import DB,CurrentUser,ProjectID,WriteKey
from app.docx_conversion import KIND,PROFILE,validate_docx
from app.storage import BlobStore,sha256
from app.api_docs import error_responses

router=APIRouter(prefix="/api/v1/projects/{project_id}/conversions",tags=["17 DOCX文档接入"])


class ConversionInput(BaseModel):
    title:str=Field(min_length=1,max_length=200,description="逻辑文档名称。")
    kind:str=Field(description="TENDER/AMENDMENT/RESPONSE/EVIDENCE。")
    document_id:str|None=Field(default=None,description="追加修订的已有逻辑文档，空则新文档。")
    raw_hash:str=Field(description="服务器读取DOCX后的摘要，不由浏览器决定。")


class ConversionResponse(BaseModel):
    id:str=Field(description="DOCX转换记录ID，原DOCX永久绑定此记录。")
    job_id:str=Field(description="转换任务ID；成功后PDF仍须继续后台解析。")
    status:str=Field(description="转换任务状态，不代表解析或业务审核完成。")
    revision_id:str|None=Field(description="完成后生成的PDF修订ID；未完成为空。")
    document_id:str|None=Field(description="完成后逻辑文档ID，或追加目标文档。")
    title:str=Field(description="文档名称。")
    error_detail:str|None=Field(description="安全的转换失败提示。")
    runtime:dict=Field(description="转换器/字体包清单与生成PDF摘要，用于追溯分页，不包含密钥。")


class RetryInput(BaseModel):
    """Explicit empty command, without instantiating abstract BaseModel."""
    pass


def dto(db,row):
    job=db.get(m.Job,row.job_id)
    return {"id":row.id,"job_id":row.job_id,"status":job.status,"revision_id":row.revision_id,
        "document_id":row.document_id,"title":row.title,"error_detail":job.error_detail,"runtime":row.runtime}


@router.post("",status_code=202,response_model=ConversionResponse,operation_id="upload_docx_conversion",
    summary="保留DOCX原件并异步渲染为不可变PDF",responses=error_responses(401,403,404,409,413,415,422),
    description="业务场景：团队使用Word编辑响应，希望在系统保留Word原件并获得固定页码的审查依据。仅OWNER/EDITOR，最多50MiB，拒绝加密、宏、过大解压与外部资源。隔离LibreOffice和字体渲染PDF，保存实际包清单/摘要，随后进入原有MinerU队列。转换202不等于解析成功；页码与坐标引用生成PDF，不声称对应Word编辑页。生成文件不自动发布为正式材料。")
async def upload(project_id:ProjectID,db:DB,user:CurrentUser,key:WriteKey,
    file:Annotated[UploadFile,File(description="真实DOCX容器文件；原件保留，可单独下载。")],
    title:Annotated[str,Form(min_length=1,max_length=200,description="文档显示名称。")],
    kind:Annotated[Literal["TENDER","AMENDMENT","RESPONSE","EVIDENCE"],Form(description="资料类型。")],
    document_id:Annotated[str|None,Form(description="可选的已有逻辑文档ID，用于追加新PDF修订。")]=None):
    _,member=b.access(db,project_id,user)
    if member.role not in b.EDIT:b.fail(403,"需要本项目编辑权限。")
    if not title.strip():b.fail(422,"文档名称不能为空。")
    content=await file.read(get_settings().max_upload_bytes+1)
    if len(content)>get_settings().max_upload_bytes:b.fail(413,"DOCX超过50MiB上传上限。")
    validate_docx(content)
    body=ConversionInput(title=title.strip(),kind=kind,document_id=document_id or None,raw_hash=sha256(content))
    def apply(db,project,actor,value):
        dedup=f"docx:{project.id}:{sha256(value.model_dump_json().encode())}:{PROFILE}"
        existing=db.scalar(select(m.Job).where(m.Job.dedup_key==dedup))
        if existing:
            return dto(db,db.scalar(select(m.DocumentConversion).where(m.DocumentConversion.job_id==existing.id)))
        if value.document_id:
            document=db.get(m.Document,value.document_id)
            if not document or document.project_id!=project.id:b.fail(404,"文档不存在。")
            if document.kind!=value.kind:b.fail(422,"追加修订须保留原资料类型。")
        cid=m.uid();raw_key=f"projects/{project.id}/docx/{value.raw_hash}.docx"
        BlobStore(get_settings().storage_path).put(raw_key,content)
        job=m.Job(project_id=project.id,revision_id=None,kind=KIND,parser_profile=PROFILE,dedup_key=dedup)
        db.add(job);db.flush()
        row=m.DocumentConversion(id=cid,project_id=project.id,document_id=value.document_id,job_id=job.id,
            title=value.title,kind=value.kind,raw_key=raw_key,raw_hash=value.raw_hash,created_by=actor.id)
        db.add(row);db.flush();db.add(m.OutboxEvent(job_id=job.id))
        return dto(db,row)
    return b.mutate(db,user,project_id,key,body,"UPLOAD_DOCX",b.EDIT,apply)


@router.get("",response_model=list[ConversionResponse],operation_id="list_docx_conversions",
    summary="查看最近的DOCX转换状态和PDF修订",responses=error_responses(401,404),
    description="本项目成员查看最近100条转换记录；完成后在资料列表找到新PDF修订，核对版式与原文，再明确发布正式材料。业务场景：Word上传202后跟踪转换进展。SUCCEEDED仅表示固定版式PDF已产生，随后仍需查看资料页解析任务。转换失败保留DOCX原件，可检查环境后明确重试；不会自动替换正式材料或沿用旧判断。")
def listing(project_id:ProjectID,db:DB,user:CurrentUser):
    b.access(db,project_id,user)
    return [dto(db,row) for row in db.scalars(select(m.DocumentConversion).where(m.DocumentConversion.project_id==project_id)
        .order_by(m.DocumentConversion.created_at.desc()).limit(100))]


@router.get("/{conversion_id}/original",response_class=FileResponse,operation_id="download_docx_original",
    summary="下载转换前的DOCX原件",responses=error_responses(401,404,503),
    description="项目成员下载原DOCX，先校验摘要。正式引用的坐标仍指向生成PDF；下载源文件不会修改任何版本。业务场景：编写人下载原始Word继续编辑。conversion_id来自转换列表；下载只返回该记录冻结的源字节，不包含后续编辑内容，不能用Word当前分页替代PDF页码。校验失败返回503，拒绝提供来源不一致的原件。")
def original(project_id:ProjectID,conversion_id:PathAnnotated[str,APIPath(description="DOCX转换记录ID，不是生成的PDF修订ID。")],db:DB,user:CurrentUser):
    b.access(db,project_id,user)
    row=db.get(m.DocumentConversion,conversion_id)
    if not row or row.project_id!=project_id:b.fail(404,"转换记录不存在。")
    store=BlobStore(get_settings().storage_path)
    try:
        if sha256(store.read(row.raw_key))!=row.raw_hash:b.fail(503,"DOCX原件校验失败。")
    except OSError:b.fail(503,"DOCX原件暂不可用。")
    return FileResponse(store.path(row.raw_key),filename="source.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.post("/{conversion_id}/retry",response_model=ConversionResponse,operation_id="retry_docx_conversion",
    summary="明确重试失败的DOCX转换",responses=error_responses(401,403,404,409),
    description="仅OWNER/EDITOR。失败后检查文件与Worker，再明确重试；复用已冻结的中间PDF检查点，避免重渲染的时间元数据导致幂等冲突。活动和完成任务不重复启动。失败重试仍需当前项目编辑权限，不授予原提交人已经失去的权限。成功后由人核对生成PDF和解析文字，再选择本轮材料。")
def retry(project_id:ProjectID,conversion_id:PathAnnotated[str,APIPath(description="DOCX转换记录ID，不是生成的PDF修订ID。")],db:DB,user:CurrentUser,key:WriteKey):
    def apply(db,project,actor,body):
        row=db.get(m.DocumentConversion,conversion_id)
        if not row or row.project_id!=project.id:b.fail(404,"转换记录不存在。")
        job=db.scalar(select(m.Job).where(m.Job.id==row.job_id).with_for_update())
        if job.status=="FAILED":
            job.status="QUEUED";job.attempt=0;job.lease_token+=1;job.lease_until=None
            job.next_attempt_at=m.utcnow();job.last_dispatched_at=None;job.error_code=job.error_detail=None
            event=db.scalar(select(m.OutboxEvent).where(m.OutboxEvent.job_id==job.id))
            if event:event.status="PENDING";event.claim_token=None;event.lease_until=None
            else:db.add(m.OutboxEvent(job_id=job.id))
        return dto(db,row)
    return b.mutate(db,user,project_id,key,RetryInput(),f"RETRY_DOCX:{conversion_id}",b.EDIT,apply)
