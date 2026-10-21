"""Formal material retrieval: MySQL facts, immutable chunks, fenced Milvus projection."""
from datetime import timedelta

from sqlalchemy import select

from app import business as b, models as m
from app.jobs import Attempt, StaleLease, heartbeat, owned_job
from app.milvus import Milvus, RetrievalUnavailable
from app.storage import sha256

PROFILE = "milvus-2.6-chinese-bm25-block1200-overlap120-v1"
KIND = "MATERIAL_INDEX"
MAX_CHUNKS = 10000


def current_index(db, project):
    return db.scalar(select(m.RetrievalIndex).where(
        m.RetrievalIndex.material_set_id == project.current_material_set_id,
        m.RetrievalIndex.profile == PROFILE))


def freeze_chunks(db, project, material, index_id):
    chunks = []
    for item in material.items:
        if item["submission_role"] == "REFERENCE":
            continue
        artifact, revision, document = b.artifact_parts(db, project.id, item["artifact_id"])
        if revision.sha256 != item["sha256"] or artifact.parser_profile != item["parser_profile"]:
            b.fail(409, "正式材料的冻结来源校验失败。")
        blocks = db.scalars(select(m.DocumentBlock).where(m.DocumentBlock.artifact_id == artifact.id)
            .order_by(m.DocumentBlock.page, m.DocumentBlock.block_id)).all()
        for block in blocks:
            if sha256(block.text.encode()) != block.text_hash:
                b.fail(409, "原文完整性校验失败，请检查解析产物。")
            for start in range(0, len(block.text), 1080):
                text = block.text[start:start + 1200]
                if not text.strip():
                    continue
                source = {"artifact_id": artifact.id, "artifact_sha256": artifact.sha256,
                    "block_id": block.block_id, "revision_id": revision.id,
                    "revision_sha256": revision.sha256, "document_id": document.id,
                    "title": document.title, "parser_profile": artifact.parser_profile,
                    "page": block.page, "bbox": block.bbox, "text_hash": block.text_hash,
                    "submission_role": item["submission_role"], "start": start, "end": start + len(text)}
                chunk_id = sha256(f"{index_id}:{artifact.id}:{block.block_id}:{start}".encode())
                chunks.append(m.RetrievalChunk(id=chunk_id, index_id=index_id, text=text, source=source))
                if len(chunks) > MAX_CHUNKS:
                    b.fail(422, "正式材料超过10000个检索片段，请拆分项目。")
    if not chunks:
        b.fail(422, "正式材料没有可检索文字，请先检查解析质量。")
    return chunks


def enqueue(db, project, actor, value):
    if value.expected_material_set_id != project.current_material_set_id:
        b.fail(409, "正式材料集已变化，请刷新后重新构建。")
    material = db.get(m.MaterialSet, project.current_material_set_id)
    if material is None:
        b.fail(409, "请先发布本轮正式材料。")
    index = current_index(db, project)
    if index:
        job = db.scalar(select(m.Job).where(m.Job.id == index.job_id).with_for_update())
        if job.status == "FAILED" and value.retry_failed or job.status == "SUCCEEDED" and value.rebuild:
            index.published_token = None  # Explicit rebuild makes old projection unavailable until complete.
            job.status = "QUEUED"; job.attempt = 0; job.lease_token += 1; job.lease_until = None
            job.next_attempt_at = m.utcnow(); job.last_dispatched_at = None
            job.error_code = None; job.error_detail = None
            event = db.scalar(select(m.OutboxEvent).where(m.OutboxEvent.job_id == job.id).with_for_update())
            if event:
                event.status = "PENDING"; event.claim_token = None; event.lease_until = None
            else:
                db.add(m.OutboxEvent(job_id=job.id))
        return {"id": index.id, "job_id": job.id, "reused": True}
    first = next(i for i in material.items if i["submission_role"] == "FORMAL_RESPONSE")
    index_id = m.uid()
    chunks = freeze_chunks(db, project, material, index_id)
    job = m.Job(project_id=project.id, revision_id=first["revision_id"], kind=KIND,
        parser_profile=PROFILE, dedup_key=f"material-index:{material.id}:{PROFILE}")
    db.add(job); db.flush()
    index = m.RetrievalIndex(id=index_id, project_id=project.id, material_set_id=material.id,
        profile=PROFILE, job_id=job.id, chunk_count=len(chunks), created_by=actor.id)
    db.add(index); db.flush(); db.add_all(chunks); db.add(m.OutboxEvent(job_id=job.id))
    return {"id": index.id, "job_id": job.id, "reused": False}


def run_index(factory, job_id, settings, client=None):
    with factory.begin() as db:
        job = db.scalar(select(m.Job).where(m.Job.id == job_id).with_for_update())
        if not job or job.kind != KIND or job.status != "QUEUED" or job.next_attempt_at > m.utcnow():
            return {"status": "IGNORED"}
        job.status = "RUNNING"; job.attempt += 1; job.lease_token += 1
        job.lease_until = m.utcnow() + timedelta(seconds=settings.lease_seconds)
        attempt = Attempt(job.id, job.project_id, job.revision_id, job.lease_token, "", "", job.parser_profile)
        index = db.scalar(select(m.RetrievalIndex).where(m.RetrievalIndex.job_id == job.id))
        index_id, total = index.id, index.chunk_count
    try:
        if not settings.retrieval_enabled or attempt.parser_profile != PROFILE:
            raise RetrievalUnavailable("检索配置未启用或版本不一致。")
        client = client or Milvus(settings)
        heartbeat(factory, attempt, settings)
        client.ensure()
        for offset in range(0, total, 100):
            heartbeat(factory, attempt, settings)
            with factory() as db:
                chunks = db.scalars(select(m.RetrievalChunk).where(m.RetrievalChunk.index_id == index_id)
                    .order_by(m.RetrievalChunk.id).offset(offset).limit(100)).all()
            client.write(attempt.project_id, f"{index_id}:{attempt.token}", chunks)
        heartbeat(factory, attempt, settings)
        with factory.begin() as db:
            # Project -> Job lock order matches HTTP mutations. Late attempts cannot publish.
            db.scalar(select(m.Project).where(m.Project.id == attempt.project_id).with_for_update())
            job = owned_job(db, attempt)
            db.get(m.RetrievalIndex, index_id).published_token = attempt.token
            job.status = "SUCCEEDED"; job.lease_until = None; job.error_code = job.error_detail = None
            db.add(m.AuditEvent(project_id=attempt.project_id, action="MATERIAL_INDEX_COMPLETED",
                object_id=index_id, details={"profile": PROFILE, "chunk_count": total, "generation": attempt.token}))
        return {"status": "SUCCEEDED", "index_id": index_id}
    except StaleLease:
        return {"status": "STALE_LEASE"}
    except Exception:
        try:
            with factory.begin() as db:
                job = owned_job(db, attempt)
                job.status = "FAILED" if job.attempt >= settings.job_max_attempts else "RETRY_WAIT"
                job.error_code = "RETRIEVAL_INDEX_ERROR"
                job.error_detail = "索引构建未完成，请检查Milvus连接后重试。"
                job.lease_until = None
                job.next_attempt_at = m.utcnow() + timedelta(seconds=min(60, 2 ** job.attempt))
        except StaleLease:
            return {"status": "STALE_LEASE"}
        return {"status": "FAILED_OR_RETRY_WAIT"}


def search(db, user, project_id, value, settings, client=None):
    project, _ = b.access(db, project_id, user)
    if value.expected_material_set_id != project.current_material_set_id:
        b.fail(409, "正式材料集已变化，请刷新后重新查询。")
    index = current_index(db, project)
    if not index or index.published_token is None or db.get(m.Job, index.job_id).status != "SUCCEEDED":
        b.fail(409, "本轮材料索引尚未就绪，请先构建并等待完成。")
    index_id, token, material_id = index.id, index.published_token, index.material_set_id
    # Finish read transaction before external search; recheck membership and input in a new snapshot.
    db.commit()
    hits = (client or Milvus(settings)).search(project_id, f"{index_id}:{token}", value.query, value.limit * 3)
    db.expire_all()
    project, _ = b.access(db, project_id, user)
    index = db.get(m.RetrievalIndex, index_id)
    if project.current_material_set_id != material_id or index.published_token != token:
        b.fail(409, "检索过程中正式材料或索引已变化，请重新查询。")
    results, seen = [], set()
    for hit in hits:
        chunk = db.get(m.RetrievalChunk, hit.get("chunk"))
        if not chunk or chunk.index_id != index_id:
            raise RetrievalUnavailable("索引来源校验失败，请重建本轮索引。")
        source = chunk.source
        block = db.get(m.DocumentBlock, (source["artifact_id"], source["block_id"]))
        if (not block or sha256(block.text.encode()) != source["text_hash"]
                or block.text[source["start"]:source["end"]] != chunk.text):
            raise RetrievalUnavailable("检索原文校验失败，请检查存储。")
        pair = (source["artifact_id"], source["block_id"])
        if pair in seen:
            continue
        seen.add(pair)
        results.append({"chunk_id": chunk.id, "score": hit["distance"], "quote": chunk.text,
            "source": source, "original_url": f"/api/v1/revisions/{source['revision_id']}/original#page={source['page']}"})
        if len(results) == value.limit:
            break
    return {"material_set_id": material_id, "index_id": index_id, "profile": PROFILE,
            "query": value.query, "results": results}
