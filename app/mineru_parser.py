"""MinerU 4 MiddleJson -> 项目稳定的文字块契约；不借用旧解析器生成结果。"""
import json
import math
import os
import re
import signal
import subprocess
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path

import pypdfium2 as pdfium

from app.parsers import ParseRejected
from app.storage import sha256

PROFILES={f"mineru-4.0.12-{tier}-{mode}-v1":(tier,mode)
          for tier,mode in (("flash","auto"),("flash","txt"),("flash","ocr"),("basic","auto"))}
DEFAULT_PROFILE="mineru-4.0.12-flash-auto-v1"


class MinerUUnavailable(RuntimeError):
    """可恢复运行环境错误，外部日志和异常原文不能进入业务响应。"""


def stop_process(process):
    # MinerU OCR can spawn render workers. Stop their isolated process group too on timeout/lost lease.
    group=os.name=="posix" and getattr(process,"pid",None)
    if group:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
    elif process.poll() is None:process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    if group:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass


class TableText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in {"script","style"}:self.hidden+=1
        elif not self.hidden and tag in {"td","th"}:self.parts.append("\t")
        elif not self.hidden and tag in {"tr","br","p"}:self.parts.append("\n")
    def handle_endtag(self,tag):
        if tag in {"script","style"}:self.hidden=max(0,self.hidden-1)
        elif not self.hidden and tag in {"tr","p"}:self.parts.append("\n")
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)
    def text(self):
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip())


def content_text(block,depth=0):
    if depth>30:raise ParseRejected("MinerU content nesting exceeds the supported limit")
    kind=block.get("type")
    # Image-generated descriptions are not verbatim PDF evidence.
    if kind=="image_body":return ""
    content=block.get("content","")
    if isinstance(content,str):
        if kind=="table_body":
            parser=TableText();parser.feed(content);return parser.text()
        return content
    if not isinstance(content,list) or any(not isinstance(child,dict) for child in content):
        raise ParseRejected("MinerU block content does not match the supported schema")
    separator="\n" if kind in {"list","index","table","image","chart","code"} else ""
    return separator.join(text for child in content if (text:=content_text(child,depth+1)))


def pdf_geometry(data,max_pages):
    try:
        with pdfium.PdfDocument(data) as document:
            if not 1<=len(document)<=max_pages:raise ParseRejected("PDF page count exceeds configured limit or is zero")
            return [document.get_page_size(index) for index in range(len(document))]
    except ParseRejected:raise
    except Exception as error:
        raise ParseRejected(f"PDF preflight failed ({type(error).__name__})") from None


def normalize(envelope,profile,geometry):
    """归一化坐标0..1乘实际PDF点尺寸；不将1000制或像素制误当PDF点。"""
    try:
        if envelope["runtime"]!={"mineru":"4.0.12","docvortex":"0.5.16"}:
            raise ValueError("runtime")
        middle=envelope["middle"]
        if middle["schema"]!="docvortex.middle" or middle["schema_version"]!="2.0" or middle["is_full_document"] is not True:
            raise ValueError("schema")
        metadata=middle["extensions"]["mineru"]
        tier,mode=PROFILES[profile]
        if metadata["tier"]!=tier or metadata["parse_mode"] not in {"txt","ocr"} or mode!="auto" and metadata["parse_mode"]!=mode:
            raise ValueError("actual parser options")
        source_pages=middle["pages"]
        if len(source_pages)!=len(geometry) or [p["page_idx"] for p in source_pages]!=list(range(len(geometry))):
            raise ValueError("missing or duplicate pages")
        layout=middle["extensions"]["docvortex_layout"]
        if layout["version"]!=1:raise ValueError("layout version")
        sizes={p["page_idx"]:(p["width_pt"],p["height_pt"]) for p in layout["pages"]}
        if len(layout["pages"])!=len(geometry) or set(sizes)!=set(range(len(geometry))):raise ValueError("page geometry")
        blocks=[];pages=[];flags=["MINERU_"+tier.upper(),"HUMAN_VERIFICATION_REQUIRED"]
        flags.append("OCR_PERFORMED" if metadata["parse_mode"]=="ocr" else "NATIVE_TEXT_MODE")
        for page,expected in zip(source_pages,geometry):
            number=page["page_idx"]+1
            width,height=sizes[number-1]
            if any(type(v) not in {int,float} or not math.isfinite(v) or v<=0 for v in (width,height)):
                raise ValueError("invalid dimensions")
            if any(abs(a-b)>1 for a,b in zip((width,height),expected)):raise ValueError("PDF geometry mismatch")
            count=0;indices=[]
            for source in page["blocks"]:
                indices.append(source["index"])
                text=content_text(source).strip()
                if not text:continue
                if len(text.encode("utf-8"))>60000:
                    raise ParseRejected("MinerU text block exceeds the 60000-byte storage limit; split the document")
                box=source["bbox"]
                if (not isinstance(box,list) or len(box)!=4 or any(type(v) not in {int,float} or not math.isfinite(v) or not 0<=v<=1 for v in box)
                        or box[2]<=box[0] or box[3]<=box[1]):raise ValueError("invalid normalized bbox")
                count+=1
                bbox=[round(v*scale,6) for v,scale in zip(box,(width,height,width,height))]
                blocks.append({"block_id":f"p{number:04d}-b{count:04d}","page":number,"bbox":bbox,
                    "text":text,"text_hash":sha256(text.encode())})
                if source["type"]=="table" and "TABLE_TEXT_FLATTENED" not in flags:flags.append("TABLE_TEXT_FLATTENED")
            if any(type(i) is not int or i<0 for i in indices) or indices!=sorted(set(indices)):raise ValueError("block order")
            pages.append({"page":number,"width":width,"height":height,"block_count":count,
                          "flags":[] if count else ["NO_EXTRACTED_TEXT_NEEDS_REVIEW"]})
        if not blocks:flags.append("NO_EXTRACTABLE_TEXT")
        if any(p["flags"] for p in pages):flags.append("PAGES_NEED_ATTENTION")
        return {"parser_profile":profile,"coordinate_system":"pdf_points_top_left","page_count":len(pages),
            "block_count":len(blocks),"pages":pages,"quality_status":"NEEDS_REVIEW","ready_for_review":False,
            "quality_flags":flags,"blocks":blocks,"mineru":{"runtime":envelope["runtime"],"actual":metadata,"middle_json":middle}}
    except ParseRejected:raise
    except (KeyError,TypeError,ValueError,IndexError,OverflowError):
        raise ParseRejected("MinerU result schema, page coverage or source coordinates failed validation") from None


def run_mineru(data,profile,settings,heartbeat):
    if profile not in PROFILES:raise ParseRejected("Unsupported MinerU profile; no silent parser fallback")
    geometry=pdf_geometry(data,settings.max_pdf_pages)
    tier,mode=PROFILES[profile]
    with tempfile.TemporaryDirectory(prefix="bid-mineru-") as temporary:
        source=Path(temporary)/"input.pdf";output=Path(temporary)/"result.json"
        source.write_bytes(data)
        heartbeat()
        try:
            process=subprocess.Popen([settings.mineru_python,str(Path(__file__).with_name("mineru_runner.py")),
                str(source),str(output),"--tier",tier,"--mode",mode],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                start_new_session=os.name=="posix",env={key:value for key,value in os.environ.items() if not key.startswith("BID_")})
        except OSError:
            raise MinerUUnavailable("MinerU runtime unavailable; use the parser worker image") from None
        started=time.monotonic()
        completed=False
        try:
            while True:
                try:code=process.wait(timeout=min(10,settings.lease_seconds/3))
                except subprocess.TimeoutExpired:
                    heartbeat()
                    if time.monotonic()-started>=settings.mineru_timeout_seconds:
                        raise MinerUUnavailable("MinerU execution timed out") from None
                    continue
                if code!=0:
                    category="SDKError"
                    if output.is_file() and output.stat().st_size<1024:
                        try:
                            value=json.loads(output.read_text()).get("error_type","")
                            if isinstance(value,str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}",value):category=value
                        except (ValueError,UnicodeError):pass
                    raise MinerUUnavailable(f"MinerU execution failed ({category}); check pinned runtime and model availability")
                break
            heartbeat()
            if not output.is_file() or output.stat().st_size>settings.mineru_max_result_bytes:
                raise ParseRejected("MinerU output is missing or exceeds the configured result limit")
            try:envelope=json.loads(output.read_text(encoding="utf-8"))
            except (ValueError,UnicodeError):raise ParseRejected("MinerU did not produce valid JSON") from None
            result=normalize(envelope,profile,geometry)
            completed=True
            return result
        finally:
            if not completed:stop_process(process)
