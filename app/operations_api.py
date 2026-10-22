import csv
import html
import io
import json
from fastapi import APIRouter,Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func,select
from app import business as b,models as m
from app.api_docs import error_responses
from app.config import get_settings
from app.dependencies import CurrentUser,DB,ProjectID
from app.extraction_model import config_snapshot,ExtractionError

router=APIRouter(prefix="/api/v1/projects/{project_id}",tags=["19 导出与运行维护"])


def stats(db,project_id):
    jobs={f"{kind}:{status}":count for kind,status,count in db.execute(select(m.Job.kind,m.Job.status,func.count())
        .where(m.Job.project_id==project_id).group_by(m.Job.kind,m.Job.status))}
    bytes_count=db.scalar(select(func.coalesce(func.sum(m.DocumentRevision.byte_size),0)).join(m.Document)
        .where(m.Document.project_id==project_id))
    indexes=db.scalar(select(func.count()).select_from(m.RetrievalIndex).where(m.RetrievalIndex.project_id==project_id))
    chunks=db.scalar(select(func.count()).select_from(m.RetrievalChunk).join(m.RetrievalIndex)
        .where(m.RetrievalIndex.project_id==project_id))
    return {"jobs":jobs,"revision_bytes":bytes_count,"indexes":indexes,"chunks":chunks}


@router.get("/operations",operation_id="get_project_operations",summary="查看本项目后台任务与检索容量",
    responses=error_responses(401,403,404),description="仅OWNER。返回按任务类型/状态统计的任务数、逻辑修订字节总数、历史索引和片段数量，以及启用的功能。字节总数可能重复计入相同内容，不代表物理磁盘用量。模型configured仅表示配置完整，不会发起付费探测；服务健康由Docker healthcheck核对。")
def operations(project_id:ProjectID,db:DB,user:CurrentUser):
    _,member=b.access(db,project_id,user)
    if member.role!="OWNER":b.fail(403,"仅负责人可查看运行维护。")
    settings=get_settings()
    try:config_snapshot(settings);configured=True
    except ExtractionError:configured=False
    return {**stats(db,project_id),"features":{"retrieval":settings.retrieval_enabled,"semantic":settings.semantic_enabled,
        "model_configured":configured},"backup_method":"python -m scripts.backup_project --output /data/blobs/backups/snapshot.zip",
        "maintenance_note":"备份包含全安装数据与认证摘要；只保存在受保护目录，不上传公共仓库。"}


@router.get("/operations/metrics",operation_id="get_project_metrics",summary="读取本项目可监控的计数指标",
    response_class=Response,responses=error_responses(401,403,404),
    description="仅OWNER，需正常认证，可由内部采集程序读取Prometheus文本格式的任务/片段计数。无项目名称、用户信息、文件正文或密钥；不代表吞吐量/延迟或生产可用率。业务场景：负责人为内部监控采集数量趋势。指标按当前认证项目隔离，采集方必须保存自己的时间序列才能观察变化；本接口仅输出即时计数，不附带公开无认证地址。")
def metrics(project_id:ProjectID,db:DB,user:CurrentUser):
    _,member=b.access(db,project_id,user)
    if member.role!="OWNER":b.fail(403,"仅负责人可读取指标。")
    data=stats(db,project_id)
    lines=[f'bid_jobs{{kind="{k.split(":")[0]}",status="{k.split(":")[1]}"}} {v}' for k,v in sorted(data["jobs"].items())]
    lines.extend(f"bid_{name} {data[name]}" for name in ("revision_bytes","indexes","chunks"))
    return Response("\n".join(lines)+"\n",media_type="text/plain; version=0.0.4")


def snapshot(db,project):
    report=b.report(db,project)
    baseline=b.baseline_dto(db,db.get(m.Baseline,project.current_baseline_id)) if project.current_baseline_id else None
    material=db.get(m.MaterialSet,project.current_material_set_id) if project.current_material_set_id else None
    return jsonable_encoder({"project":{"id":project.id,"name":project.name},"generated_at":m.utcnow(),"report":report,
        "baseline":baseline,"material_set":{"id":material.id,"version":material.version,"items":material.items} if material else None})


@router.get("/review-report/export.json",operation_id="export_review_json",summary="导出含冻结依据的JSON审查快照",
    response_class=Response,responses=error_responses(401,404),
    description="项目成员导出当前报告、要求基线、正式材料与引文摘要，供系统间归档。保留未完成项，不将模型建议写成人工结论；不包含密钥或Cookie。此时点快照不会阻止后续版本变更。业务场景：项目归档或外部工具处理，使用本文件保留本轮依据。下载文件需要受保护存储；PDF原件仍通过带权限的原件接口取得，导出不会扩大任何项目的访问范围。")
def export_json(project_id:ProjectID,db:DB,user:CurrentUser):
    project,_=b.access(db,project_id,user)
    return Response(json.dumps(snapshot(db,project),ensure_ascii=False,indent=2),media_type="application/json",
        headers={"Content-Disposition":'attachment; filename="review-report.json"',"Cache-Control":"no-store"})


@router.get("/review-report/export.csv",operation_id="export_review_csv",summary="导出逐项覆盖清单CSV",
    response_class=Response,responses=error_responses(401,404),
    description="项目成员导出便于表格筛选的要求标题、状态、未解决数和人工意见。UTF8 BOM，危险公式开头加单引号以便Excel安全打开；完整原文与版本见JSON/Markdown。业务场景：团队在表格中整理未核对项。CSV只用于浏览和归档，不提供批量导回或覆盖审核结论的能力；请以当前工作台版本和有出处的人工判断为准。")
def export_csv(project_id:ProjectID,db:DB,user:CurrentUser):
    project,_=b.access(db,project_id,user);data=b.report(db,project)
    stream=io.StringIO();writer=csv.writer(stream)
    writer.writerow(["要求ID","标题","状态","未解决问题","人工意见"])
    def safe(value):
        text=str(value)
        return "'"+text if text.startswith(("=","+","-","@","\t","\r")) else text
    for row in data["requirements"]:
        writer.writerow([safe(row["requirement_id"]),safe(row["title"]),row["status"],row["unresolved_issue_count"],
            safe((row["current_decision"] or {}).get("note",""))])
    return Response("\ufeff"+stream.getvalue(),media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":'attachment; filename="review-report.csv"',"Cache-Control":"no-store"})


@router.get("/review-report/print",operation_id="print_review_report",summary="打开可打印及保存PDF的报告版式",
    response_class=Response,responses=error_responses(401,404),
    description="项目成员打开专用打印页面，再使用浏览器打印/另存PDF。服务器返回HTML而非已生成PDF，标题、意见和引文均转义，不执行文档脚本。报告保留当前完成状态和来源摘要。业务场景：项目成员准备纸质或PDF交付件。使用浏览器打印后检查分页与字体，生成件是下载时点的报告，后续材料变化不会更新已保存文件；需要新版本时重新导出。")
def print_report(project_id:ProjectID,db:DB,user:CurrentUser):
    project,_=b.access(db,project_id,user);data=snapshot(db,project);report=data["report"]
    escape=lambda value:html.escape(str(value))
    requirements={row["requirement_id"]:row for row in (data["baseline"] or {}).get("requirements",[])}
    sections=[]
    for row in report["requirements"]:
        requirement=requirements[row["requirement_id"]];decision=row["current_decision"] or {}
        refs=requirement["sources"]+decision.get("evidence",[])
        quotes="".join(f'<blockquote>{escape(ref["quote"])}<small>实际第{ref["page"]}页 / SHA256 {escape(ref["revision_sha256"])}</small></blockquote>' for ref in refs)
        sections.append(f'<section><h2>{escape(row["title"])}</h2><p>{escape(requirement["text"])}</p><p>{escape(row["status"])} / 待解决{row["unresolved_issue_count"]}</p><p>{escape(decision.get("note","待人工判断"))}</p>{quotes}</section>')
    content=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>核标审查报告</title>
    <style>body{{font:15px/1.8 sans-serif;color:#203641;max-width:900px;margin:40px auto;padding:24px}}h1{{font-size:26px}}h2{{font-size:18px}}section{{border-top:1px solid #ccd8dc;padding:20px 0}}blockquote{{margin:16px 0;padding:12px;border-left:3px solid #146b5c;white-space:pre-wrap;overflow-wrap:anywhere}}small{{display:block;font-size:11px}}@media print{{@page{{margin:18mm}}body{{margin:0;padding:0}}h2{{break-after:avoid}}blockquote{{break-inside:avoid}}}}</style>
    <h1>{escape(project.name)}：审查报告</h1><p>状态：{escape(report["status"])}；人工覆盖{report["reviewed_count"]}/{report["requirement_count"]}；待解决{report["unresolved_issue_count"]}</p>
    <p>未发布或待处理更正：{escape(report["pending_requirement_changes"])}。本报告保留人工判断，模型建议不作为最终结论。</p><small>生成时间UTC：{escape(data["generated_at"])}</small>{"".join(sections)}</html>'''
    return Response(content,media_type="text/html",headers={"Cache-Control":"no-store",
        "Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'"})
