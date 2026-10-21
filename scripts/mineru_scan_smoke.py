"""将固定构造PDF的一页栅格化，验证真实MinerU自动选择OCR；不是OCR准确率评测。"""
import io
import json
from pathlib import Path

import pypdfium2 as pdfium

from app.config import get_settings
from app.mineru_parser import DEFAULT_PROFILE,run_mineru


def main():
    source=Path(__file__).resolve().parent.parent/"app/demo_assets/tender.pdf"
    with pdfium.PdfDocument(source) as document:
        page=document[1]
        bitmap=page.render(scale=2)
        image=bitmap.to_pil().convert("RGB")
        stream=io.BytesIO();image.save(stream,"PDF",resolution=144)
        image.close();bitmap.close();page.close()
    result=run_mineru(stream.getvalue(),DEFAULT_PROFILE,get_settings(),lambda:None)
    text="".join("".join(b["text"].split()) for b in result["blocks"])
    assert "OCR_PERFORMED" in result["quality_flags"]
    assert "2小时" in text and "2次" in text
    print(json.dumps({"engine":"REAL_MINERU_SDK","input":"synthetic_image_only_pdf","pages":result["page_count"],
        "actual":result["mineru"]["actual"],"response_clause_found":True,"training_clause_found":True},ensure_ascii=False))


if __name__=="__main__":main()
