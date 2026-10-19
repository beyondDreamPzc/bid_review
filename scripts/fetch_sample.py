"""Download one verified public procurement sample. No vendor documents are bundled."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

URL = "https://sh-gov-open-doc.oss-cn-shanghai.aliyuncs.com/1108QZ/1d6463c5-b281-4d49-9e3d-ad5c447a45ad.pdf"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/samples/shanghai-12345-2023.pdf"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(URL, timeout=60) as response:
        content = response.read(30 * 1024 * 1024 + 1)
    if not content.startswith(b"%PDF-") or len(content) > 30 * 1024 * 1024:
        raise RuntimeError("Download was not an acceptable PDF")
    args.output.write_bytes(content)
    metadata = {"title": "12345 市民感知平台建设费（二期）采购项目",
                "procurement_year": 2023, "source_url": URL,
                "source_kind": "public_government_procurement", "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content), "expected_pages": 65,
                "purpose": "Text-layer and source-location verification; historical sample, not current bidding guidance"}
    args.output.with_suffix(".source.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(args.output), "sha256": metadata["sha256"], "bytes": len(content)}))


if __name__ == "__main__":
    main()
