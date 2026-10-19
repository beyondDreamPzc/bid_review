"""Package source without local secrets, data or caches."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parent.parent
destination = root.parent / "bid-review-source.zip"
excluded_directories = {".git", ".idea", ".vscode", ".venv", "__pycache__", ".pytest_cache", "data", "htmlcov"}
files = []
for file in root.rglob("*"):
    relative = file.relative_to(root)
    if not file.is_file() or any(part in excluded_directories for part in relative.parts):
        continue
    if file.name == ".env" or file.suffix in {".pyc", ".zip"}:
        continue
    if file.name in {"sample-smoke.json", "mysql-invariants.json", "business-smoke.json"}:
        continue
    files.append((file, relative))
with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
    for file, relative in sorted(files):
        archive.write(file, Path(root.name) / relative)
with ZipFile(destination) as archive:
    assert not any(Path(name).name == ".env" for name in archive.namelist())
    assert archive.testzip() is None
print(f"Packaged {len(files)} files: {destination.name}")
