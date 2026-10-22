"""Download only pinned non-executable ONNX/tokenizer assets, verify SHA256 before atomic promotion."""
import hashlib
import json
import os
from pathlib import Path
import urllib.request


def main():
    project = Path(__file__).resolve().parent.parent
    manifest = json.loads((project / "config/semantic-models.json").read_text(encoding="utf-8"))
    target = Path(os.environ.get("BID_SEMANTIC_MODELS_PATH", str(project / "data/semantic")))
    for name in ("embedding", "reranker"):
        spec = manifest[name]
        for relative, expected in spec["files"].items():
            path = target / name / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
                continue
            url = f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/{relative}"
            temporary = path.with_suffix(path.suffix + ".partial")
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk); output.write(chunk)
            if digest.hexdigest() != expected:
                temporary.unlink(missing_ok=True)
                raise RuntimeError("Downloaded model checksum mismatch")
            temporary.replace(path)
            print(json.dumps({"model":name,"file":relative,"sha256_verified":True}), flush=True)
    print("Pinned local semantic models ready", flush=True)


if __name__ == "__main__":main()
