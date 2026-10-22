"""人工业务规则。项目行锁串行化写入，事实与每次审核决定均保留历史。"""
import json
from collections import Counter

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select

from app import models as m
from app import business_schemas as s
from app.storage import sha256

EDIT = {"OWNER", "EDITOR"}
REVIEW = {"OWNER", "REVIEWER"}


def fail(status, message):
    raise HTTPException(status, message)


def access(db, project_id, user):
    if user.disabled:fail(401,"账号已停用。")
    project = db.get(m.Project, project_id)
    member = db.get(m.ProjectMember, (project_id, user.id))
    if project is None or member is None:
        fail(404, "Project not found")
    return project, member


def mutate(db, user, project_id, key, body, operation, roles, handler):
    # Authentication performed a read. End that snapshot before waiting for the
    # project lock, so MySQL REPEATABLE READ cannot see a pre-lock business state.
    db.commit()
    db.expire_all()  # Callers may have loaded task/project objects before entering this serialized write.
    project = db.scalar(select(m.Project).where(m.Project.id == project_id)
                        .with_for_update().execution_options(populate_existing=True))
    member = db.get(m.ProjectMember, (project_id, user.id), populate_existing=True)
    if project is None or member is None:
        fail(404, "Project not found")
    if user.disabled:fail(401,"账号已停用。")
    if roles and member.role not in roles:
        fail(403, "Project role cannot perform this action")
    scope = f"{user.id}:{project_id}:{operation}"
    request_hash = sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True,
                                     ensure_ascii=False, separators=(",", ":")).encode())
    record = db.get(m.IdempotencyRecord, (scope, key))
    if record:
        if record.request_hash != request_hash:
            fail(409, "Idempotency key was already used for a different request")
        response = record.response
        db.commit()  # Replays must release the project lock, too.
        return response
    result = handler(db, project, user, body)
    response = jsonable_encoder(result)
    from app.lifecycle import notify_mutation
    notify_mutation(db,project,user,operation,response)
    db.add(m.IdempotencyRecord(scope=scope, key=key, request_hash=request_hash, response=response))
    db.add(m.AuditEvent(project_id=project_id, actor_id=user.id,
                        action=operation.split(":")[0],
                        object_id=response.get("id", response.get("requirement_id", project_id)),
                        details={"operation": operation, "request_hash": request_hash,
                                 "epoch": project.review_epoch, "mode": "HUMAN"}))
    db.commit()
    return response


def dto(model, row):
    return model.model_validate(row, from_attributes=True).model_dump(mode="json")


def req_dto(row):
    return {"requirement_id": row.requirement_id, "revision_id": row.id,
            **{name: getattr(row, name) for name in (
                "revision_no", "title", "text", "category", "priority", "status",
                "sources", "created_by", "confirmed_by", "created_at")}}


def latest_requirements(db, project_id, include_retired=False):
    statement=select(m.RequirementRevision).join(m.Requirement,
        m.Requirement.id == m.RequirementRevision.requirement_id).where(
        m.Requirement.project_id == project_id)
    if not include_retired:statement=statement.where(m.Requirement.retired==False)
    rows=db.scalars(statement.order_by(m.RequirementRevision.requirement_id,m.RequirementRevision.revision_no.desc())).all()
    latest = {}
    for row in rows:
        latest.setdefault(row.requirement_id, row)
    return list(latest.values())


def requirement(db, project_id, requirement_id):
    row = db.get(m.Requirement, requirement_id)
    if row is None or row.project_id != project_id:
        fail(404, "Requirement not found")
    return row


def latest_revision(db, requirement_id):
    return db.scalar(select(m.RequirementRevision).where(
        m.RequirementRevision.requirement_id == requirement_id).order_by(
        m.RequirementRevision.revision_no.desc()).limit(1))


def artifact_parts(db, project_id, artifact_id):
    artifact = db.get(m.ParseArtifact, artifact_id)
    if artifact is None:
        fail(404, "Source artifact not found")
    revision = db.get(m.DocumentRevision, artifact.revision_id)
    document = db.get(m.Document, revision.document_id)
    if document.project_id != project_id:
        fail(404, "Source artifact not found")
    return artifact, revision, document


def sources(db, project, references, *, tender=False, formal=False):
    roles = {}
    if not tender:
        if not project.current_material_set_id:
            fail(409, "Publish a formal material set first")
        material = db.get(m.MaterialSet, project.current_material_set_id)
        roles = {item["artifact_id"]: item["submission_role"] for item in material.items}
    snapshots = []
    seen = set()
    for reference in references:
        pair = (reference.artifact_id, reference.block_id)
        if pair in seen:
            fail(422, "Duplicate source reference")
        seen.add(pair)
        artifact, revision, document = artifact_parts(db, project.id, reference.artifact_id)
        block = db.get(m.DocumentBlock, pair)
        if block is None:
            fail(404, "Source block not found")
        role = None if tender else roles.get(artifact.id)
        if tender and document.kind not in {"TENDER", "AMENDMENT"}:
            fail(422, "A requirement source must be a tender or amendment")
        if not tender and role is None:
            fail(409, "Evidence is not in the current material set")
        if formal and role == "REFERENCE":
            fail(422, "Reference-only material cannot prove a formal response")
        snapshots.append({"artifact_id": artifact.id, "block_id": block.block_id,
            "revision_id": revision.id, "document_id": document.id, "document_kind": document.kind,
            "revision_sha256": revision.sha256, "page": block.page, "bbox": block.bbox,
            "quote": block.text, "text_hash": block.text_hash, "submission_role": role})
    if formal and not snapshots:
        fail(422, "At least one formal source is required")
    return snapshots


def check_epoch(project, expected):
    if project.review_epoch != expected:
        fail(409, "Project inputs changed; refresh workspace and recheck the current sources")


def current_item(db, project, revision_id=None, requirement_id=None):
    if not project.current_baseline_id or not project.current_material_set_id:
        fail(409, "Publish both a requirements baseline and formal material set first")
    statement = select(m.BaselineItem).where(m.BaselineItem.baseline_id == project.current_baseline_id)
    if revision_id:
        statement = statement.where(m.BaselineItem.requirement_revision_id == revision_id)
    else:
        statement = statement.where(m.BaselineItem.requirement_id == requirement_id)
    item = db.scalar(statement)
    if item is None:
        fail(409, "Requirement revision is not in the current baseline")
    if db.get(m.Requirement,item.requirement_id).retired:
        fail(409,"要求已退休，请恢复并重新发布基线后操作。")
    return item


def is_current(project, snapshot):
    return bool(snapshot and snapshot.epoch == project.review_epoch
                and snapshot.baseline_id == project.current_baseline_id
                and snapshot.material_set_id == project.current_material_set_id)


def set_member(db, project, user, body):
    target = db.get(m.User, body.user_id)
    if target is None:
        fail(404, "User not found; provision the account with the bootstrap CLI")
    if target.disabled:fail(422,"该账号已停用，不能加入或调整项目角色。")
    member = db.get(m.ProjectMember, (project.id, target.id))
    if body.expected_role is not None and (not member or member.role!=body.expected_role):
        fail(409,"成员角色已变化，请刷新后重新核对。")
    if member and member.role == "OWNER":
        fail(409, "The owner role cannot be changed through this endpoint")
    if body.role not in EDIT and db.scalar(select(m.WorkItem.id).where(
            m.WorkItem.project_id == project.id, m.WorkItem.assignee_id == target.id,m.WorkItem.status!="CANCELLED").limit(1)):
        fail(409, "A task assignee must retain an editor role for future rechecks")
    if member:
        member.role = body.role
    else:
        db.add(m.ProjectMember(project_id=project.id, user_id=target.id, role=body.role))
    db.flush()
    return {"user_id": target.id, "name": target.name, "role": body.role}


def create_requirement(db, project, user, body, requirement_id=None):
    revision_no = 1
    if requirement_id:
        if requirement(db, project.id, requirement_id).retired:fail(409,"请先恢复要求再修订。")
        previous = latest_revision(db, requirement_id)
        if previous.revision_no != body.expected_revision_no:
            fail(409, "Requirement revision changed; reload before editing")
        revision_no = previous.revision_no + 1
    else:
        logical = m.Requirement(project_id=project.id, created_by=user.id)
        db.add(logical)
        db.flush()
        requirement_id = logical.id
    row = m.RequirementRevision(requirement_id=requirement_id, revision_no=revision_no,
        title=body.title, text=body.text, category=body.category, priority=body.priority,
        sources=sources(db, project, body.sources, tender=True), created_by=user.id, status="DRAFT")
    db.add(row)
    db.flush()
    return req_dto(row)


def confirm_requirement(db, project, user, body, requirement_id):
    if requirement(db, project.id, requirement_id).retired:fail(409,"请先恢复要求再确认。")
    row = latest_revision(db, requirement_id)
    if row.revision_no != body.expected_revision_no:
        fail(409, "Requirement revision changed; reload before confirming")
    if row.status == "DRAFT":
        row.status, row.confirmed_by = "CONFIRMED", user.id
        db.flush()
    return req_dto(row)


def baseline_dto(db, row):
    revisions = db.scalars(select(m.RequirementRevision).join(m.BaselineItem,
        m.BaselineItem.requirement_revision_id == m.RequirementRevision.id).where(
        m.BaselineItem.baseline_id == row.id).order_by(m.RequirementRevision.requirement_id))
    return {"id": row.id, "project_id": row.project_id, "version": row.version, "name": row.name,
            "parent_id": row.parent_id, "created_by": row.created_by, "created_at": row.created_at,
            "requirements": [req_dto(revision) for revision in revisions]}


def publish_baseline(db, project, user, body):
    check_epoch(project, body.expected_epoch)
    if body.expected_current_baseline_id != project.current_baseline_id:
        fail(409, "Current baseline changed")
    latest = latest_requirements(db, project.id)
    expected = {row.id for row in latest}
    if (not latest and not latest_requirements(db,project.id,include_retired=True)) or any(row.status != "CONFIRMED" for row in latest):
        fail(409, "All latest requirement revisions must be confirmed before publication")
    if len(body.requirement_revision_ids) != len(expected) or set(body.requirement_revision_ids) != expected:
        fail(409, "Publish exactly all latest confirmed requirements, without omissions or duplicates")
    version = (db.scalar(select(func.max(m.Baseline.version)).where(m.Baseline.project_id == project.id)) or 0) + 1
    row = m.Baseline(project_id=project.id, version=version, name=body.name,
                     parent_id=project.current_baseline_id, created_by=user.id)
    db.add(row)
    db.flush()
    db.add_all([m.BaselineItem(baseline_id=row.id, requirement_id=revision.requirement_id,
                              requirement_revision_id=revision.id) for revision in latest])
    project.current_baseline_id = row.id
    project.review_epoch += 1
    db.flush()
    return baseline_dto(db, row)


def publish_materials(db, project, user, body):
    check_epoch(project, body.expected_epoch)
    if body.expected_current_material_set_id != project.current_material_set_id:
        fail(409, "Current material set changed")
    items, seen_documents = [], set()
    for selection in body.items:
        artifact, revision, document = artifact_parts(db, project.id, selection.artifact_id)
        if document.kind not in {"RESPONSE", "EVIDENCE"}:
            fail(422, "A material set accepts only response and evidence documents")
        if selection.submission_role == "FORMAL_RESPONSE" and document.kind != "RESPONSE":
            fail(422, "FORMAL_RESPONSE requires a RESPONSE document")
        if document.id in seen_documents:
            fail(422, "Select only one artifact/version per logical document")
        seen_documents.add(document.id)
        items.append({"artifact_id": artifact.id, "submission_role": selection.submission_role,
            "revision_id": revision.id, "document_id": document.id, "title": document.title,
            "document_kind": document.kind, "sha256": revision.sha256, "parser_profile": artifact.parser_profile})
    if not any(item["submission_role"] == "FORMAL_RESPONSE" for item in items):
        fail(422, "Select at least one FORMAL_RESPONSE document")
    version = (db.scalar(select(func.max(m.MaterialSet.version)).where(m.MaterialSet.project_id == project.id)) or 0) + 1
    row = m.MaterialSet(project_id=project.id, version=version, name=body.name, items=items, created_by=user.id)
    db.add(row)
    db.flush()
    project.current_material_set_id = row.id
    project.review_epoch += 1
    return dto(s.MaterialSetResponse, row)


def task_dto(db, project, task):
    issue = db.get(m.ReviewIssue, task.issue_id)
    submission = db.get(m.TaskSubmission, task.current_submission_id) if task.current_submission_id else None
    current = is_current(project, submission or issue)
    effective = "NEEDS_RECHECK" if task.status in {"SUBMITTED", "ACCEPTED"} and not current else task.status
    decisions = db.scalars(select(m.TaskDecision).where(m.TaskDecision.task_id == task.id)
                           .order_by(m.TaskDecision.task_version))
    return {"id": task.id, "issue_id": task.issue_id, "requirement_id": issue.requirement_id,
        "assignee_id": task.assignee_id, "due_date": task.due_date, "status": task.status,
        "effective_status": effective, "freshness": "CURRENT" if current else "STALE", "version": task.version,
        "current_submission": dto(s.SubmissionResponse, submission) if submission else None,
        "decisions": [dto(s.TaskDecisionResponse, row) for row in decisions]}


def issue_dto(db, project, issue):
    task = db.scalar(select(m.WorkItem).where(m.WorkItem.issue_id == issue.id))
    task_data = task_dto(db, project, task)
    status = "OPEN"
    if task.status == "ACCEPTED":
        status = "RESOLVED" if task_data["freshness"] == "CURRENT" else "NEEDS_RECHECK"
    if issue.withdrawn:status="WITHDRAWN"
    return {**{name: getattr(issue, name) for name in (
        "id", "requirement_id", "requirement_revision_id", "baseline_id", "material_set_id",
        "epoch", "title", "description", "kind", "severity", "evidence")},
        "status": status, "freshness": "CURRENT" if is_current(project, issue) else "STALE", "task": task_data}


def create_issue(db, project, user, body):
    check_epoch(project, body.expected_epoch)
    item = current_item(db, project, revision_id=body.requirement_revision_id)
    assignee = db.get(m.ProjectMember, (project.id, body.assignee_id))
    if assignee is None or assignee.role not in EDIT:
        fail(422, "Assignee must be an OWNER or EDITOR in this project")
    if db.get(m.User,body.assignee_id).disabled:fail(422,"请选择未停用的整改负责人。")
    evidence = sources(db, project, body.evidence, formal=body.kind == "CONFLICT")
    logical = db.get(m.Requirement, item.requirement_id)
    logical.review_version += 1  # A newly discovered issue invalidates prior satisfaction, even in the same epoch.
    issue = m.ReviewIssue(project_id=project.id, requirement_id=item.requirement_id,
        requirement_revision_id=item.requirement_revision_id, baseline_id=project.current_baseline_id,
        material_set_id=project.current_material_set_id, epoch=project.review_epoch, title=body.title,
        description=body.description, kind=body.kind, severity=body.severity, evidence=evidence, created_by=user.id)
    db.add(issue)
    db.flush()
    db.add(m.WorkItem(project_id=project.id, issue_id=issue.id,
                      assignee_id=body.assignee_id, due_date=body.due_date))
    db.flush()
    return issue_dto(db, project, issue)


def get_task(db, project_id, task_id):
    task = db.get(m.WorkItem, task_id)
    if task is None or task.project_id != project_id:
        fail(404, "Task not found")
    return task


def transition_task(db, project, user, body, task_id):
    task = get_task(db, project.id, task_id)
    member = db.get(m.ProjectMember, (project.id, user.id))
    if task.assignee_id != user.id or member.role not in EDIT:
        fail(403, "Only the assigned editor/owner can change this task")
    if task.version != body.expected_version:
        fail(409, "Task version changed; reload before acting")
    check_epoch(project, body.expected_epoch)
    issue = db.get(m.ReviewIssue, task.issue_id)
    if body.action == "START":
        old = db.get(m.TaskSubmission, task.current_submission_id) if task.current_submission_id else None
        stale_submission = task.status in {"SUBMITTED", "ACCEPTED"} and not is_current(project, old)
        if task.status not in {"TODO", "RETURNED"} and not stale_submission:
            fail(409, "Task cannot start in its current state")
        task.status = "IN_PROGRESS"
        task.version += 1
    else:
        if task.status != "IN_PROGRESS":
            fail(409, "Start the task before submitting")
        if not body.note.strip():
            fail(422, "A remediation note is required")
        item = current_item(db, project, requirement_id=issue.requirement_id)
        row = m.TaskSubmission(task_id=task.id, task_version=task.version + 1,
            requirement_revision_id=item.requirement_revision_id, baseline_id=project.current_baseline_id,
            material_set_id=project.current_material_set_id, epoch=project.review_epoch,
            note=body.note, evidence=sources(db, project, body.evidence, formal=True), submitted_by=user.id)
        db.add(row)
        db.flush()
        task.status, task.current_submission_id = "SUBMITTED", row.id
        task.version += 1
    db.flush()
    return task_dto(db, project, task)


def decide_task(db, project, user, body, task_id):
    task = get_task(db, project.id, task_id)
    if task.version != body.expected_version or task.status != "SUBMITTED" or task.current_submission_id != body.submission_id:
        fail(409, "Task state/version/submission changed; reload before review")
    submission = db.get(m.TaskSubmission, task.current_submission_id)
    if submission.submitted_by == user.id:
        fail(403, "The submitter cannot review their own remediation")
    if not is_current(project, submission):
        fail(409, "Inputs changed after submission; the assignee must recheck and resubmit")
    task.status = "ACCEPTED" if body.decision == "ACCEPT" else "RETURNED"
    task.version += 1
    db.add(m.TaskDecision(task_id=task.id, submission_id=submission.id, task_version=task.version,
                          decision=body.decision, note=body.note, decided_by=user.id))
    db.flush()
    return task_dto(db, project, task)


def open_issues(db, project):
    counts = Counter()
    issues = db.scalars(select(m.ReviewIssue).where(m.ReviewIssue.project_id == project.id))
    for issue in issues:
        if issue.withdrawn:continue
        task = db.scalar(select(m.WorkItem).where(m.WorkItem.issue_id == issue.id))
        submission = db.get(m.TaskSubmission, task.current_submission_id) if task.current_submission_id else None
        if task.status != "ACCEPTED" or not is_current(project, submission):
            counts[issue.requirement_id] += 1
    return counts


def decide_requirement(db, project, user, body):
    check_epoch(project, body.expected_epoch)
    item = current_item(db, project, revision_id=body.requirement_revision_id)
    if db.scalar(select(m.ChangeImpact.id).where(m.ChangeImpact.requirement_id==item.requirement_id,
            m.ChangeImpact.disposition=="PENDING")):
        fail(409,"请先处理该要求的更正影响，再作最终判断。")
    count = open_issues(db, project)[item.requirement_id]
    if body.decision in {"CONFIRMED_SATISFIED", "NOT_APPLICABLE"} and count:
        fail(409, "Resolve and independently accept every issue before completing this requirement")
    if body.decision == "CONFIRMED_ISSUE" and not count:
        fail(409, "Register an actionable issue and assignee first")
    evidence = sources(db, project, body.evidence, formal=body.decision == "CONFIRMED_SATISFIED")
    sequence = (db.scalar(select(func.max(m.RequirementDecision.sequence)).where(
        m.RequirementDecision.requirement_id == item.requirement_id)) or 0) + 1
    row = m.RequirementDecision(requirement_id=item.requirement_id,
        requirement_revision_id=item.requirement_revision_id, baseline_id=project.current_baseline_id,
        material_set_id=project.current_material_set_id, epoch=project.review_epoch, sequence=sequence,
        review_version=db.get(m.Requirement, item.requirement_id).review_version,
        decision=body.decision, note=body.note, evidence=evidence, decided_by=user.id)
    db.add(row)
    db.flush()
    return dto(s.RequirementDecisionResponse, row)


def pending_changes(db, project):
    latest = {row.requirement_id: row.id for row in latest_requirements(db, project.id)}
    frozen = {row.requirement_id: row.requirement_revision_id for row in db.scalars(
        select(m.BaselineItem).where(m.BaselineItem.baseline_id == project.current_baseline_id))}
    return latest != frozen or bool(db.scalar(select(m.ChangeImpact.id).where(
        m.ChangeImpact.project_id==project.id,m.ChangeImpact.disposition=="PENDING").limit(1)))


def report(db, project):
    counts, rows = open_issues(db, project), []
    items = db.scalars(select(m.BaselineItem).where(
        m.BaselineItem.baseline_id == project.current_baseline_id).order_by(m.BaselineItem.requirement_id))
    for item in items:
        revision = db.get(m.RequirementRevision, item.requirement_revision_id)
        logical = db.get(m.Requirement, item.requirement_id)
        decision = db.scalar(select(m.RequirementDecision).where(
            m.RequirementDecision.requirement_revision_id == revision.id,
            m.RequirementDecision.baseline_id == project.current_baseline_id,
            m.RequirementDecision.material_set_id == project.current_material_set_id,
            m.RequirementDecision.epoch == project.review_epoch,
            m.RequirementDecision.review_version == logical.review_version).order_by(
            m.RequirementDecision.sequence.desc()).limit(1))
        status = "UNREVIEWED"
        if counts[item.requirement_id]:
            status = "ISSUES_OPEN"
        elif decision:
            status = "REVIEWED" if decision.decision in {"CONFIRMED_SATISFIED", "NOT_APPLICABLE"} else "NEEDS_REVIEW"
        rows.append({"requirement_id": item.requirement_id, "requirement_revision_id": revision.id,
            "title": revision.title, "status": status, "unresolved_issue_count": counts[item.requirement_id],
            "current_decision": dto(s.RequirementDecisionResponse, decision) if decision else None})
    reviewed = sum(row["status"] == "REVIEWED" for row in rows)
    unresolved = sum(row["unresolved_issue_count"] for row in rows)
    pending = pending_changes(db, project)
    ready = bool(project.current_baseline_id and project.current_material_set_id)
    complete = ready and bool(rows) and reviewed == len(rows) and not unresolved and not pending
    status = "NOT_READY" if not ready else "ISSUES_OPEN" if unresolved else "REVIEW_COMPLETE" if complete else "IN_REVIEW"
    return {"project_id": project.id, "baseline_id": project.current_baseline_id,
        "material_set_id": project.current_material_set_id, "review_epoch": project.review_epoch,
        "review_mode": "HUMAN", "status": status, "manual_review_complete": complete,
        "pending_requirement_changes": pending, "requirement_count": len(rows), "reviewed_count": reviewed,
        "unresolved_issue_count": unresolved, "requirements": rows}
