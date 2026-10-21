"""在隔离环境运行真实 MinerU SDK；通过文件传递结果，不在日志中输出原文。"""
import argparse
import importlib.metadata
import json
from pathlib import Path


def main():
    args=argparse.ArgumentParser()
    args.add_argument("source");args.add_argument("output")
    args.add_argument("--tier",choices=["flash","basic"],required=True)
    args.add_argument("--mode",choices=["auto","txt","ocr"],required=True)
    values=args.parse_args()
    try:
        versions={name:importlib.metadata.version(name) for name in ("mineru","docvortex")}
        if versions!={"mineru":"4.0.12","docvortex":"0.5.16"}:
            raise RuntimeError("Unexpected parser dependency versions")
        from mineru.parser import parse
        # SDK empty range means the entire document, unlike the document-library CLI's first-10-page default.
        result=parse(values.source,tier=values.tier,ocr_mode=values.mode,image_analysis=False,page_range="")
        Path(values.output).write_text(json.dumps({"runtime":versions,"middle":result.to_dict()},ensure_ascii=False),encoding="utf-8")
    except Exception as error:
        # Preserve a useful category without exposing PDF contents, filesystem paths or remote response bodies.
        Path(values.output).write_text(json.dumps({"error_type":type(error).__name__}),encoding="utf-8")
        raise SystemExit(2) from None


if __name__=="__main__":main()
