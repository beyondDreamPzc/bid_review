from typing import Annotated as PathAnnotated
from fastapi import Path as APIPath
"""Local account lifecycle and project-scoped in-app notifications. No external messaging."""
from typing import Annotated
from fastapi import APIRouter,Query,Request
from pydantic import BaseModel,Field,SecretStr
from sqlalchemy import delete,func,select
from app import business as b,models as m
from app.dependencies import CurrentUser,DB,WriteKey
from app.lifecycle_schemas import PageResponse
from app.session_auth import COOKIE_NAME
from app.storage import sha256
from app.api_docs import error_responses

router=APIRouter(prefix="/api/v1",tags=["16 账号与站内通知"])


class RotateKeyInput(BaseModel):
    new_key: SecretStr=Field(min_length=24,max_length=256,description="用户已安全保存的新随机密钥，仅通过请求发送；数据库只存SHA256，不写幂等响应、审计或浏览器存储。")
    expected_fingerprint: str=Field(min_length=12,max_length=12,description="账号设置显示的当前密钥摘要前12位，防止并发轮换覆盖。不是登录凭据。")


class AccountResponse(BaseModel):
    user_id: str=Field(description="当前实际用户ID。")
    name: str=Field(description="当前账号名称。")
    key_fingerprint: str=Field(description="当前API Key SHA256前12位，仅用于核对版本。")
    sessions: list[dict]=Field(description="有效会话列表，只包含ID、到期时间与是否当前浏览器，不含令牌。")


class AccountAction(BaseModel):
    completed: bool=Field(description="请求动作已完成。")
    login_required: bool=Field(description="是否需要用新密钥重新登录。")


@router.get("/account",response_model=AccountResponse,operation_id="get_account_security",
    summary="查看自己的密钥版本与有效会话",responses=error_responses(401),
    description="用于本人检查访问凭据和其他浏览器会话。只返回本人会话ID及到期时间，不返回密钥、令牌或其他账号信息。业务场景：更换电脑或检查账号安全时，先取得当前密钥指纹与会话清单。指纹只用于并发版本校验，不能用来登录。撤销会话与更换密钥分别调用对应写接口，本读取不延长会话有效期。")
def account(db:DB,user:CurrentUser,request:Request):
    token=request.cookies.get(COOKIE_NAME,"")
    return {"user_id":user.id,"name":user.name,"key_fingerprint":user.api_key_hash[:12],
        "sessions":[{"id":s.id,"expires_at":s.expires_at,"current":s.token_hash==sha256(token.encode())}
            for s in db.scalars(select(m.WebSession).where(m.WebSession.user_id==user.id,m.WebSession.expires_at>m.utcnow()))]}


@router.post("/account/key",response_model=AccountAction,operation_id="rotate_own_api_key",
    summary="轮换本人访问密钥并撤销全部会话",responses=error_responses(401,409,422),
    description="业务场景：密钥到期或怀疑泄露。本人先安全保存新随机密钥，再携带当前fingerprint提交。事务内锁定账号，只存新摘要，撤销所有Cookie会话；旧密钥立即失效。幂等摘要包含新密钥的摘要而非明文，网络失败可用新密钥按同键重试。成功后必须重新登录，不修改项目角色。")
def rotate(body:RotateKeyInput,db:DB,user:CurrentUser,key:WriteKey):
    user_id=user.id;db.commit();db.expire_all()
    actor=db.scalar(select(m.User).where(m.User.id==user_id).with_for_update())
    if actor.disabled:b.fail(401,"账号已停用。")
    new_hash=sha256(body.new_key.get_secret_value().encode())
    request_hash=sha256((body.expected_fingerprint+new_hash).encode())
    scope=f"account-key:{user_id}"
    previous=db.get(m.IdempotencyRecord,(scope,key))
    if previous:
        if previous.request_hash!=request_hash:b.fail(409,"该幂等键已用于另一轮换请求。")
        result=previous.response;db.commit();return result
    if actor.api_key_hash[:12]!=body.expected_fingerprint:b.fail(409,"密钥已被更新，请重新核对账号设置。")
    if actor.api_key_hash==new_hash:b.fail(422,"新密钥必须与旧密钥不同。")
    if db.scalar(select(m.User.id).where(m.User.api_key_hash==new_hash)):b.fail(422,"此密钥不可用，请另生成随机密钥。")
    actor.api_key_hash=new_hash
    db.execute(delete(m.WebSession).where(m.WebSession.user_id==user_id))
    result={"completed":True,"login_required":True}
    db.add(m.IdempotencyRecord(scope=scope,key=key,request_hash=request_hash,response=result));db.commit()
    return result


@router.post("/account/sessions/{session_id}/revoke",response_model=AccountAction,
    operation_id="revoke_own_session",summary="撤销本人的一个浏览器会话",responses=error_responses(401,404),
    description="本人在账号设置撤销遗留设备会话。不能撤销其他人的会话；重复撤销返回404。操作立即影响下一次认证，若撤销当前会话则需要重新登录。无需改变API Key。请先读取账号安全清单，确认目标会话ID；撤销其他设备不会退出当前设备，撤销当前设备后应返回登录页面。")
def revoke(session_id:PathAnnotated[str,APIPath(description="本人有效会话ID，从账号安全接口取得，不是Cookie令牌。")],db:DB,user:CurrentUser,request:Request):
    session=db.get(m.WebSession,session_id)
    if not session or session.user_id!=user.id:b.fail(404,"会话不存在。")
    current=session.token_hash==sha256(request.cookies.get(COOKIE_NAME,"").encode())
    db.delete(session);db.commit();return {"completed":True,"login_required":current}


@router.get("/notifications",response_model=PageResponse,operation_id="list_in_app_notifications",
    summary="查看本人仍有项目权限的站内通知",responses=error_responses(401),
    description="任务指派、提交复核、复核结果和审查输入变化的站内提醒。只显示本人且仍为项目成员的记录；被移除后不泄露项目标题。不会发送邮件、短信或第三方消息。通过offset和limit翻页，unread=true仅显示未读。点击通知前可单独标记已读；通知中的项目链接仍须重新鉴权。提醒不是任务完成或人工验收的证明。")
def notifications(db:DB,user:CurrentUser,unread:bool=Query(default=False,description="true仅查看未读。"),
        offset:int=Query(default=0,ge=0,description="从0开始的偏移。"),
        limit:int=Query(default=20,ge=1,le=100,description="每页上限。")):
    statement=select(m.Notification).join(m.ProjectMember,(m.ProjectMember.project_id==m.Notification.project_id)&
        (m.ProjectMember.user_id==m.Notification.user_id)).where(m.Notification.user_id==user.id)
    if unread:statement=statement.where(m.Notification.read_at.is_(None))
    total=db.scalar(select(func.count()).select_from(statement.subquery()))
    records=db.scalars(statement.order_by(m.Notification.created_at.desc(),m.Notification.id).offset(offset).limit(limit))
    return {"items":[{"id":row.id,"title":row.title,"project_id":row.project_id,"section":row.section,
        "created_at":row.created_at,"read_at":row.read_at} for row in records],"total":total,"offset":offset,"limit":limit}


@router.post("/notifications/{notification_id}/read",response_model=AccountAction,
    operation_id="read_in_app_notification",summary="将本人通知标记为已读",responses=error_responses(401,404),
    description="只允许通知接收人且仍有项目权限时标记，重复标记保持原已读时间，不改变业务任务或审核结论。业务场景：用户查看过通知后消除未读标记。notification_id来自本人通知清单，不接受项目ID替代；无权访问统一404。此接口不提交整改、不变更任务状态，也不会触发外部邮件或消息。")
def read_notification(notification_id:PathAnnotated[str,APIPath(description="本人通知ID，从站内通知列表取得。")],db:DB,user:CurrentUser):
    row=db.get(m.Notification,notification_id)
    if not row or row.user_id!=user.id:b.fail(404,"通知不存在。")
    b.access(db,row.project_id,user)
    if row.read_at is None:row.read_at=m.utcnow()
    db.commit();return {"completed":True,"login_required":False}
