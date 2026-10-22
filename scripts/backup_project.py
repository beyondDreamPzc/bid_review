"""Logical installation backup with immutable blob hashes. Restore only into an empty target."""
import argparse
from datetime import date,datetime
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import tempfile
from zipfile import ZipFile,ZIP_DEFLATED

from sqlalchemy import Date,DateTime,select,text
from app.config import get_settings
from app.database import Base,SessionLocal,make_engine
from app import models as m
from app.storage import BlobStore

HEAD="0008_delivery"


def digest_file(path):
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        while chunk:=stream.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()


def backup(destination):
    target=Path(destination).resolve()
    if target.exists():raise RuntimeError("Backup destination exists; choose a new file")
    target.parent.mkdir(parents=True,exist_ok=True)
    store=BlobStore(get_settings().storage_path)
    tables={};blobs={}
    with SessionLocal() as db:
        if db.bind.dialect.name=="mysql":db.connection(execution_options={"isolation_level":"REPEATABLE READ"})
        heads=list(db.scalars(text("SELECT version_num FROM alembic_version")))
        if heads!=[HEAD]:raise RuntimeError("Database migration differs from this backup tool")
        for table in Base.metadata.sorted_tables:
            rows=[dict(row) for row in db.execute(select(table)).mappings()]
            tables[table.name]=[] if table.name=="web_sessions" else rows
            if table.name in {"document_revisions","parse_artifacts"}:
                blobs.update({row["storage_key"]:row["sha256"] for row in rows})
            if table.name=="document_conversions":
                blobs.update({row["raw_key"]:row["raw_hash"] for row in rows})
                blobs.update({row["runtime"]["pdf_key"]:row["runtime"]["pdf_sha256"] for row in rows if row["runtime"].get("pdf_key")})
    fd,temporary=tempfile.mkstemp(prefix=".backup-",suffix=".zip",dir=target.parent);os.close(fd)
    os.chmod(temporary,0o600)
    try:
        manifest={"format":1,"head":HEAD,"created_at":m.utcnow().isoformat()+"Z","tables":{},"blobs":{}}
        with ZipFile(temporary,"w",ZIP_DEFLATED) as archive:
            for name,rows in tables.items():
                data=json.dumps(rows,ensure_ascii=False,default=lambda value:value.isoformat()).encode()
                archive.writestr(f"tables/{name}.json",data)
                manifest["tables"][name]={"sha256":hashlib.sha256(data).hexdigest(),"rows":len(rows),"bytes":len(data)}
            for key,expected in blobs.items():
                path=store.path(key)
                if digest_file(path)!=expected:raise RuntimeError("Source blob integrity mismatch; backup aborted")
                archive.write(path,"blobs/"+key)
                manifest["blobs"][key]={"sha256":expected,"bytes":path.stat().st_size}
            archive.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False).encode())
        os.replace(temporary,target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(json.dumps({"backup_created":True,"tables":len(tables),"blobs":len(blobs),"sessions_excluded":True}))


def verify(path):
    with ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist())>20*1024**3:raise RuntimeError("Backup exceeds 20GiB safety limit")
        manifest=json.loads(archive.read("manifest.json"))
        if manifest.get("format")!=1 or manifest.get("head")!=HEAD:raise RuntimeError("Unsupported backup schema")
        expected={"manifest.json"}|{f"tables/{name}.json" for name in manifest["tables"]}|{"blobs/"+key for key in manifest["blobs"]}
        if len(archive.namelist())!=len(expected) or set(archive.namelist())!=expected:raise RuntimeError("Unexpected or duplicate backup entries")
        for group,prefix in (("tables","tables/"),("blobs","blobs/")):
            for key,info in manifest[group].items():
                relative=key+".json" if group=="tables" else key
                parsed=PurePosixPath(relative)
                if parsed.is_absolute() or ".." in parsed.parts or ":" in relative or "\\" in relative:
                    raise RuntimeError("Unsafe backup path")
                digest=hashlib.sha256();size=0
                with archive.open(prefix+relative) as stream:
                    while chunk:=stream.read(1024*1024):digest.update(chunk);size+=len(chunk)
                if digest.hexdigest()!=info["sha256"] or size!=info["bytes"]:raise RuntimeError("Backup integrity mismatch")
        return manifest


def restore(path,target_env,blob_root):
    manifest=verify(path)
    target_url=os.environ.get(target_env,"")
    if not target_url:raise RuntimeError("Set the target database URL in the named environment variable")
    if target_url==get_settings().database_url:raise RuntimeError("Restore target must differ from the active installation")
    engine=make_engine(target_url)
    from sqlalchemy import inspect
    if inspect(engine).get_table_names():raise RuntimeError("Restore requires an empty target database, not an existing installation")
    store=BlobStore(Path(blob_root))
    if any(store.root.iterdir()):raise RuntimeError("Restore requires an empty target blob directory")
    if set(manifest["tables"])!={t.name for t in Base.metadata.sorted_tables}:raise RuntimeError("Backup tables differ from this release")
    Base.metadata.create_all(engine)
    with ZipFile(path) as archive,engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            rows=json.loads(archive.read(f"tables/{table.name}.json"))
            for row in rows:
                for column in table.columns:
                    if row.get(column.name) is not None:
                        if isinstance(column.type,DateTime):row[column.name]=datetime.fromisoformat(row[column.name])
                        elif isinstance(column.type,Date):row[column.name]=date.fromisoformat(row[column.name])
                if table.name=="jobs" and row["status"] in {"QUEUED","RUNNING","RETRY_WAIT"}:
                    row["status"]="RETRY_WAIT";row["lease_token"]+=1;row["lease_until"]=None;row["next_attempt_at"]=m.utcnow()
                if table.name=="retrieval_indexes":row["published_token"]=None
            if rows:connection.execute(table.insert(),rows)
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES (:head)"),{"head":HEAD})
        connection.execute(text("UPDATE jobs SET status='FAILED', error_code='RESTORED_REBUILD_REQUIRED', error_detail='Restored installation: rebuild material index', lease_until=NULL, lease_token=lease_token+1 WHERE kind='MATERIAL_INDEX'"))
        for key in manifest["blobs"]:store.put(key,archive.read("blobs/"+key))
    engine.dispose()
    print(json.dumps({"restored_to_empty_target":True,"sessions_revoked":True,"material_index_rebuild_required":True}))


def main():
    parser=argparse.ArgumentParser(description="Protected installation backup and empty-target restore")
    parser.add_argument("--output");parser.add_argument("--verify");parser.add_argument("--restore")
    parser.add_argument("--target-env",default="BID_RESTORE_DATABASE_URL")
    parser.add_argument("--blob-root")
    args=parser.parse_args()
    if sum(bool(v) for v in (args.output,args.verify,args.restore))!=1:parser.error("Choose output, verify or restore")
    if args.output:backup(args.output)
    elif args.verify:verify(args.verify);print("Backup file hashes verified; this does not replace a restore drill")
    else:
        if not args.blob_root:parser.error("Restore requires --blob-root pointing to a new empty directory")
        restore(args.restore,args.target_env,args.blob_root)


if __name__=="__main__":main()
