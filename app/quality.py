"""基于冻结解析产物的可解释诊断，不重新解析、不修改来源块。"""
import math
import re
from collections import defaultdict

PROFILE = "text-quality-v1"
LIMITATIONS = ["仅检查已提取文字，无法证明没有漏字。", "不识别扫描图像，也不执行 OCR。",
               "不重建表格、跨栏阅读顺序或合并单元格；复杂页面必须回看原件。"]


def finding(code, severity, message, suggestion, ids=None):
    ids = ids or []
    return {"code": code, "severity": severity, "message": message, "suggestion": suggestion,
            "affected_block_count": len(ids), "block_ids": ids[:20]}


def page_diagnostics(page, blocks):
    chars = sum(len("".join(b["text"].split())) for b in blocks)
    bad = [b["block_id"] for b in blocks if "\ufffd" in b["text"] or re.search(r"\(cid:\d+\)", b["text"])]
    findings = []
    if not blocks:
        findings.append(finding("NO_TEXT", "WARNING", "本页没有可提取文字。",
            "打开原件，区分真实空白、图片/扫描页或提取失败；有内容时需提供文字层或后续 OCR。"))
    elif chars < 30:
        findings.append(finding("SPARSE_TEXT", "INFO", "本页提取文字少于30个非空白字符。",
            "可能只是封面或分隔页；请核对是否还有图片中的文字未提取。"))
    if bad:
        findings.append(finding("SUSPECT_ENCODING", "WARNING", "文字含替代字符或未映射的 CID 字形。",
            "回看对应原文；必要时重新导出带正确字体映射的 PDF。不要直接作为 AI 判断依据。", bad))
    width, height = float(page["width"]), float(page["height"])
    invalid, valid = [], []
    for block in blocks:
        box = [float(n) for n in block["bbox"]]
        x0, y0, x1, y1 = box
        if (not all(math.isfinite(n) for n in box) or x1 <= x0 or y1 <= y0
                or x0 < -1 or y0 < -1 or x1 > width + 1 or y1 > height + 1):
            invalid.append(block["block_id"])
        else:
            valid.append((box, block["block_id"]))
    if invalid:
        findings.append(finding("INVALID_BBOX", "WARNING", "部分文字块的位置超出页面或矩形无效。",
            "页码和位置可能不可靠，请回看原件；后续更换解析配置时保留旧产物。", invalid))
    # Only compare adjacent spatial neighbours: bounded linear scan after sorting.
    # This is an indicator, not a table/reading-order detector.
    overlaps = set()
    valid.sort(key=lambda pair: (pair[0][1], pair[0][0]))
    for (a, aid), (c, cid) in zip(valid, valid[1:]):
        intersection = max(0, min(a[2], c[2]) - max(a[0], c[0])) * max(0, min(a[3], c[3]) - max(a[1], c[1]))
        smaller = min((a[2]-a[0])*(a[3]-a[1]), (c[2]-c[0])*(c[3]-c[1]))
        if intersection / smaller >= 0.8:
            overlaps.update([aid, cid])
    if overlaps:
        findings.append(finding("OVERLAPPING_BLOCKS", "WARNING", "相邻文字块大幅重叠，可能存在重复文字层。",
            "核对是否重字或顺序异常；本规则不能判断表格与多栏布局是否正确。", sorted(overlaps)))
    return {"page": page["page"], "width": width, "height": height, "block_count": len(blocks),
            "character_count": chars, "findings": findings}


def diagnose(payload):
    by_page = defaultdict(list)
    for block in payload["blocks"]:
        by_page[block["page"]].append(block)
    return [page_diagnostics(page, by_page[page["page"]]) for page in payload["pages"]]
