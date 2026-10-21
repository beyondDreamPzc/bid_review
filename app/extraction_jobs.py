"""带租约与检查点的抽取执行；模型请求始终在数据库事务之外。"""
import copy
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app import models as m
from app.extraction_model import PROMPT_PROFILE, ExtractionError, config_snapshot, extract_batch
from app.extraction_service import KIND, candidate_fingerprint, verify_input
from app.jobs import Attempt, StaleLease, heartbeat, owned_job


def run_extraction(factory,job_id,settings,transport=None):
    with factory.begin() as db:
        job=db.scalar(select(m.Job).where(m.Job.id==job_id).with_for_update())
        if not job or job.kind!=KIND or job.status!="QUEUED" or job.next_attempt_at>m.utcnow():
            return {"status":"IGNORED"}
        job.status="RUNNING"; job.attempt+=1; job.lease_token+=1
        job.lease_until=m.utcnow()+timedelta(seconds=settings.lease_seconds)
        revision=db.get(m.DocumentRevision,job.revision_id)
        attempt=Attempt(job.id,job.project_id,revision.id,job.lease_token,revision.storage_key,revision.sha256,job.parser_profile)
    try:
        with factory() as db:
            run=db.scalar(select(m.ExtractionRun).where(m.ExtractionRun.job_id==job_id))
            config=config_snapshot(settings)
            if run.prompt_profile!=PROMPT_PROFILE or config!=run.model_config_snapshot:
                raise ExtractionError("MODEL_CONFIG_CHANGED","模型或提示词配置已变化，请新建抽取任务。")
            run_id, count=run.id,len(run.batches)
        for index in range(count):
            with factory() as db:
                run=db.get(m.ExtractionRun,run_id)
                verify_input(db,run,require_creator=True)
                batch=copy.deepcopy(run.batches[index])
            if batch["result"] is not None:
                continue
            heartbeat(factory,attempt,settings)
            result=extract_batch(config,settings.llm_api_key,batch["blocks"],f"{run_id}:{index}",transport)
            with factory.begin() as db:
                owned_job(db,attempt)
                run=db.get(m.ExtractionRun,run_id)
                batches=copy.deepcopy(run.batches)
                batches[index]["result"]=result
                run.batches=batches
            heartbeat(factory,attempt,settings)
        with factory.begin() as db:
            # Same lock order as API mutations: project, then job.
            db.scalar(select(m.Project).where(m.Project.id==attempt.project_id).with_for_update())
            job=owned_job(db,attempt)
            run=db.get(m.ExtractionRun,run_id)
            verify_input(db,run,require_creator=True)
            seen=set()
            for batch in run.batches:
                sources={b["block_id"]:b for b in batch["blocks"]}
                for proposed in batch["result"]["candidates"]:
                    refs=[sources[block_id] for block_id in proposed["block_ids"]]
                    fingerprint=candidate_fingerprint(proposed,refs)
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                    if len(seen)>200:
                        raise ExtractionError("MODEL_OUTPUT_LIMIT","本次候选超过200条，请缩小范围后重试。")
                    db.add(m.RequirementCandidate(run_id=run.id,project_id=run.project_id,fingerprint=fingerprint,
                        proposed=proposed,sources=refs))
            job.status="SUCCEEDED"; job.error_code=None; job.error_detail=None; job.lease_until=None
            run.completed_at=m.utcnow()
            db.add(m.AuditEvent(project_id=run.project_id,actor_id=None,action="REQUIREMENT_EXTRACTION_COMPLETED",
                object_id=run.id,details={"candidate_count":len(seen),"prompt_profile":run.prompt_profile}))
        return {"status":"SUCCEEDED","run_id":run_id}
    except StaleLease:
        return {"status":"STALE_LEASE"}
    except Exception as error:
        if isinstance(error,HTTPException):
            error=ExtractionError("EXTRACTION_INPUT_UNAVAILABLE","冻结原文或输入版本无法验证，请检查存储和质量意见。")
        if not isinstance(error,ExtractionError):
            error=ExtractionError("EXTRACTION_PROCESSING_ERROR","抽取处理异常，请检查服务日志中的错误类别；未记录文档内容。",True)
        try:
            with factory.begin() as db:
                job=owned_job(db,attempt)
                terminal=not error.retryable or job.attempt>=settings.job_max_attempts
                job.status="FAILED" if terminal else "RETRY_WAIT"
                job.error_code=error.code; job.error_detail=str(error); job.lease_until=None
                job.next_attempt_at=m.utcnow()+timedelta(seconds=min(60,2**job.attempt))
                if terminal:
                    db.scalar(select(m.ExtractionRun).where(m.ExtractionRun.job_id==job_id)).completed_at=m.utcnow()
        except StaleLease:
            return {"status":"STALE_LEASE"}
        return {"status":"FAILED_OR_RETRY_WAIT","error_code":error.code}
