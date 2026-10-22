"""Syntax and local asset checks only. No DB, Docker, browser, test or model requests."""
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def main():
    root=Path(__file__).resolve().parent.parent
    python_files=[p for folder in ("app","scripts","migrations","tests") for p in (root/folder).rglob("*.py")]
    for path in python_files:ast.parse(path.read_text(encoding="utf-8-sig"),filename=str(path))
    assets=root/"app/static";references=0
    for page in assets.glob("*.html"):
        for name in re.findall(r'(?:src|href)="/assets/([^"?]+)',page.read_text(encoding="utf-8")):
            if not (assets/name).is_file():raise RuntimeError(f"Missing asset: {name}")
            references+=1
    node=os.environ.get("BID_NODE") or shutil.which("node")
    if not node:raise RuntimeError("Node is required for JS syntax; set BID_NODE to its absolute executable path")
    scripts=list(assets.glob("*.js"))
    for path in scripts:subprocess.run([node,"--check",str(path)],check=True,capture_output=True,text=True)
    page_scripts={}
    for page in assets.glob("*.html"):
        names=re.findall(r'<script src="/assets/([^"?]+)',page.read_text(encoding="utf-8"))
        combined="\n".join((assets/name).read_text(encoding="utf-8") for name in names)
        subprocess.run([node,"--check"],input=combined,check=True,capture_output=True,text=True,encoding="utf-8")
        page_scripts[page.name]=len(names)
    documents=[root/"config/semantic-models.json",root/"evaluation/retrieval-corpus.json",root/"docs/openapi.json"]
    for path in documents:json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps({"scope":"static syntax and asset references only","python_files":len(python_files),"javascript_files":len(scripts),"page_scripts_in_load_order":page_scripts,"asset_references":references,"json_documents":len(documents),"runtime_validation":False}))


if __name__=="__main__":main()
