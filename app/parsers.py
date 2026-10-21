"""Text-layer diagnostic, not the formal Docling/table/OCR pipeline."""
import io
from collections.abc import Callable

import pdfplumber

from app.storage import sha256

PROFILE = "pdfplumber-probe-v1"
PARSE_JOB_KINDS = ("PDF_TEXT_PROBE", "PDF_PARSE")


class ParseRejected(ValueError):
    pass


def parse_pdf(data,profile,settings,heartbeat):
    # Historical queued jobs retain their frozen engine; never reinterpret an old profile.
    if profile==PROFILE:return probe_pdf(data,settings.max_pdf_pages,heartbeat)
    from app.mineru_parser import run_mineru
    return run_mineru(data,profile,settings,heartbeat)


def probe_pdf(data: bytes, max_pages: int, heartbeat: Callable[[], None]) -> dict:
    blocks = []
    pages = []
    flags = ["PROVISIONAL_TEXT_LAYER_ONLY", "TABLE_STRUCTURE_NOT_VALIDATED", "OCR_NOT_PERFORMED"]
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not 1 <= len(pdf.pages) <= max_pages:
                raise ParseRejected("PDF page count exceeds configured limit or is zero")
            for page_number, page in enumerate(pdf.pages, 1):
                heartbeat()
                lines = page.extract_text_lines(layout=False, strip=True, return_chars=False)
                nonempty = [line for line in lines if line["text"].strip()]
                pages.append({"page": page_number, "width": page.width, "height": page.height,
                              "block_count": len(nonempty),
                              "flags": [] if nonempty else ["EMPTY_TEXT_LAYER_NEEDS_OCR"]})
                for index, line in enumerate(nonempty, 1):
                    text = line["text"]
                    bbox = [round(float(line[k]), 3) for k in ("x0", "top", "x1", "bottom")]
                    blocks.append({"block_id": f"p{page_number:04d}-b{index:04d}", "page": page_number,
                                   "bbox": bbox, "text": text, "text_hash": sha256(text.encode())})
                page.close()
    except ParseRejected:
        raise
    except (OSError, MemoryError):
        raise
    except Exception as exc:
        raise ParseRejected(f"PDF cannot be read ({type(exc).__name__})") from exc
    if not blocks:
        flags.append("NO_EXTRACTABLE_TEXT")
    if any(page["flags"] for page in pages):
        flags.append("PAGES_NEED_ATTENTION")
    return {"parser_profile": PROFILE, "coordinate_system": "pdf_points_top_left",
            "page_count": len(pages), "block_count": len(blocks), "pages": pages,
            "quality_status": "NEEDS_REVIEW", "ready_for_review": False,
            "quality_flags": flags, "blocks": blocks}
