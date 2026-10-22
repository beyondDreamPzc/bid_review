"""DOCX -> immutable PDF. Raw source retained; renderer runs outside database transactions."""
from datetime import timedelta
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from xml.etree import ElementTree
from urllib.parse import urlsplit
from zipfile import ZipFile,BadZipFile

from sqlalchemy import select
from app import business as b,models as m
from app.jobs import Attempt,StaleLease,heartbeat,owned_job
from app.mineru_parser import stop_process
from app.services import ingest_pdf
from app.storage import BlobStore,sha256

KIND="DOCX_CONVERT"
PROFILE="libreoffice-snapshot20261021-noto-pdf-v1"


def validate_docx(content):
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            files=archive.infolist()
            if len(files)>5000 or sum(f.file_size for f in files)>100*1024*1024:
                b.fail(422,"DOCX解压内容超过限制。")
            names={f.filename for f in files}
            if len(names)!=len(files):b.fail(415,"DOCX含重复容器条目。")
            if not {"[Content_Types].xml","word/document.xml"}<=names:b.fail(415,"文件不是有效DOCX。")
            if b"macroenabled" in archive.read("[Content_Types].xml").lower():b.fail(415,"不接收含宏的文档类型。")
            for file in files:
                name=file.filename.lower()
                if file.flag_bits&1 or "vbaproject" in name:b.fail(415,"不接收加密或含宏的文档。")
                if "word/embeddings/" in name:b.fail(422,"请移除DOCX中嵌入的可执行对象后上传。")
                if name.endswith(".rels"):
                    relationships=ElementTree.fromstring(archive.read(file))
                    if any(node.get("TargetMode", "").lower()=="external" or urlsplit(node.get("Target", "")).scheme
                            or node.get("Target", "").startswith("//") for node in relationships):
                        b.fail(422,"DOCX含外部链接资源，请嵌入资源并移除外链后上传。")
                if name.startswith("word/") and name.endswith(".xml"):
                    xml=ElementTree.fromstring(archive.read(file))
                    if re.search(r"\b(INCLUDEPICTURE|INCLUDETEXT|DDEAUTO|DDE)\b","".join(xml.itertext()),re.I):
                        b.fail(422,"DOCX含外部字段，请转换为静态内容后上传。")
    except (BadZipFile,KeyError,RuntimeError,ElementTree.ParseError):
        b.fail(415,"DOCX已损坏或加密。")


def render_docx(content,settings,pulse):
    validate_docx(content)
    with tempfile.TemporaryDirectory(prefix="bid-docx-") as folder:
        root=Path(folder);source=root/"input.docx";source.write_bytes(content)
        profile=root/"profile";profile.mkdir()
        # Highest macro security in an isolated profile. Reject external resources before rendering.
        (profile/"user").mkdir()
        (profile/"user/registrymodifications.xcu").write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" '
            'oor:op="fuse"><value>3</value></prop></item></oor:items>',encoding="utf-8")
        environment={k:v for k,v in os.environ.items() if not k.startswith("BID_")}
        process=subprocess.Popen([settings.libreoffice_path,f"-env:UserInstallation={profile.as_uri()}",
            "--headless","--nologo","--nodefault","--nofirststartwizard","--convert-to","pdf:writer_pdf_Export",
            "--outdir",str(root),str(source)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            env=environment,start_new_session=os.name!="nt")
        deadline=time.monotonic()+100
        try:
            while process.poll() is None:
                pulse()
                if time.monotonic()>deadline:raise RuntimeError("DOCX conversion timeout")
                try:process.wait(timeout=8)
                except subprocess.TimeoutExpired:pass
            pdf=root/"input.pdf"
            if process.returncode or not pdf.is_file() or pdf.stat().st_size>settings.max_upload_bytes:
                raise RuntimeError("DOCX did not produce an accepted PDF")
            data=pdf.read_bytes()
            if not data.startswith(b"%PDF-"):raise RuntimeError("Invalid rendered PDF")
            manifest=Path(__file__).resolve().parent.parent/"config/conversion-runtime.txt"
            if not manifest.is_file():raise RuntimeError("Conversion package manifest missing")
            return data,{"profile":PROFILE,"packages":manifest.read_text(),
                "pdf_sha256":sha256(data)}
        finally:
            if process.poll() is None:stop_process(process)


def run_conversion(factory,job_id,settings):
    with factory.begin() as db:
        job=db.scalar(select(m.Job).where(m.Job.id==job_id).with_for_update())
        if not job or job.kind!=KIND or job.status!="QUEUED" or job.next_attempt_at>m.utcnow():return {"status":"IGNORED"}
        job.status="RUNNING";job.attempt+=1;job.lease_token+=1
        job.lease_until=m.utcnow()+timedelta(seconds=settings.lease_seconds)
        attempt=Attempt(job.id,job.project_id,"",job.lease_token,"","",job.parser_profile)
        conversion=db.scalar(select(m.DocumentConversion).where(m.DocumentConversion.job_id==job_id))
        cid,raw_key,expected,checkpoint=conversion.id,conversion.raw_key,conversion.raw_hash,dict(conversion.runtime)
    try:
        store=BlobStore(settings.storage_path);content=store.read(raw_key)
        if sha256(content)!=expected:raise RuntimeError("DOCX integrity mismatch")
        if checkpoint.get("pdf_key"):
            pdf=store.read(checkpoint["pdf_key"]);runtime=checkpoint
            if sha256(pdf)!=checkpoint["pdf_sha256"]:raise RuntimeError("Rendered PDF integrity mismatch")
        else:
            pdf,runtime=render_docx(content,settings,lambda:heartbeat(factory,attempt,settings))
            pdf_key=f"conversions/{cid}/{sha256(pdf)}.pdf";store.put(pdf_key,pdf)
            runtime={**runtime,"pdf_key":pdf_key}
            with factory.begin() as db:
                owned_job(db,attempt)
                db.get(m.DocumentConversion,cid).runtime=runtime
        with factory() as db:
            db.scalar(select(m.Project).where(m.Project.id==attempt.project_id).with_for_update())
            owned_job(db,attempt)
            conversion=db.get(m.DocumentConversion,cid);actor=db.get(m.User,conversion.created_by)
            project,member=b.access(db,conversion.project_id,actor)
            if member.role not in b.EDIT:b.fail(403,"DOCX提交人已不具备编辑权限。")
            # ingest_pdf commits its transaction; this transaction already holds Project and Job locks.
            conversion.runtime=runtime
            result=ingest_pdf(db,store,actor,project.id,pdf,conversion.title,conversion.kind,
                f"conversion-{cid}",settings.parser_profile,document_id=conversion.document_id)
        with factory.begin() as db:
            db.scalar(select(m.Project).where(m.Project.id==attempt.project_id).with_for_update())
            job=owned_job(db,attempt);conversion=db.get(m.DocumentConversion,cid)
            conversion.document_id=result["document_id"];conversion.revision_id=result["revision_id"]
            job.revision_id=result["revision_id"];job.status="SUCCEEDED";job.lease_until=None
            job.error_code=job.error_detail=None
            db.add(m.AuditEvent(project_id=attempt.project_id,action="DOCX_CONVERSION_COMPLETED",object_id=cid,
                details={"raw_sha256":expected,"revision_id":result["revision_id"],"runtime":runtime}))
        return {"status":"SUCCEEDED","conversion_id":cid,"revision_id":result["revision_id"]}
    except StaleLease:return {"status":"STALE_LEASE"}
    except Exception:
        try:
            with factory.begin() as db:
                job=owned_job(db,attempt)
                job.status="FAILED" if job.attempt>=settings.job_max_attempts else "RETRY_WAIT"
                job.error_code="DOCX_CONVERSION_ERROR";job.error_detail="DOCX转换未完成，请检查文件、转换Worker和字体配置。"
                job.lease_until=None;job.next_attempt_at=m.utcnow()+timedelta(seconds=min(60,2**job.attempt))
        except StaleLease:return {"status":"STALE_LEASE"}
        return {"status":"FAILED_OR_RETRY_WAIT"}
