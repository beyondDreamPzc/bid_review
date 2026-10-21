"""可复现的页码/短句检查点评测；不是全量准确率或模型业务效果。"""
import argparse
import json
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.parsers import parse_pdf
from app.config import get_settings
from app.quality import PROFILE as QUALITY_PROFILE, diagnose
from app.storage import sha256


def normalize(value):
    return "".join(unicodedata.normalize("NFKC",value).split())


def evaluate(manifest, directory, settings=None):
    settings=settings or get_settings()
    documents = []
    for case in manifest["documents"]:
        content = (directory / case["file"]).resolve().read_bytes()
        parsed = parse_pdf(content,settings.parser_profile,settings,lambda: None)
        by_page = defaultdict(list)
        for block in parsed["blocks"]:
            by_page[block["page"]].append(block["text"])
        checkpoints = [{"index":index, "page":point["page"],
            "matched":normalize(point["text"]) in normalize("\n".join(by_page[point["page"]])),
            "strict_matched":"".join(point["text"].split()) in "".join("\n".join(by_page[point["page"]]).split())}
            for index, point in enumerate(case["checkpoints"],1)]
        pages = diagnose(parsed)
        documents.append({"id":case["id"], "source_sha256":sha256(content), "page_count":parsed["page_count"],
            "page_count_matches":parsed["page_count"]==case["expected_page_count"], "checkpoints":checkpoints,
            "warning_page_count":sum(any(f["severity"]=="WARNING" for f in page["findings"]) for page in pages)})
    total = sum(len(d["checkpoints"]) for d in documents)
    matched = sum(p["matched"] for d in documents for p in d["checkpoints"])
    return {"dataset_id":manifest["dataset_id"], "parser_profile":settings.parser_profile, "diagnostic_profile":QUALITY_PROFILE,
        "document_count":len(documents), "checkpoint_count":total, "matched_checkpoint_count":matched,
        "comparison_profile":"unicode-nfkc-whitespace-v1",
        "strict_matched_checkpoint_count":sum(p["strict_matched"] for d in documents for p in d["checkpoints"]),
        "checkpoint_match_rate":matched/total if total else None,
        "all_labeled_checks_passed":bool(total) and matched==total and all(d["page_count_matches"] for d in documents),
        "limitations":"只评价已标注短句是否在指定页出现，不评价漏项、语义、表格顺序、OCR或法律合规。", "documents":documents}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT/"evaluation"/"extraction"/"manifest.json")
    parser.add_argument("--output", type=Path, default=get_settings().storage_path/"evaluation"/"extraction-report.json")
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding="utf-8"))
    result=evaluate(manifest,args.manifest.resolve().parent)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({key:result[key] for key in ("dataset_id","document_count","checkpoint_count","matched_checkpoint_count","strict_matched_checkpoint_count","comparison_profile","all_labeled_checks_passed")},ensure_ascii=False))
    if not result["all_labeled_checks_passed"]:
        raise SystemExit(1)


if __name__=="__main__":
    main()
