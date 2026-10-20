"""API 身份与数据库依赖，文档接口和业务接口共用同一认证入口。"""
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Path, Request
from fastapi.security import APIKeyCookie, APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, WebSession, utcnow
from app.session_auth import COOKIE_NAME, same_origin
from app.storage import sha256

DB = Annotated[Session, Depends(get_db)]
key_header = APIKeyHeader(name="X-API-Key", scheme_name="ApiKeyAuth", auto_error=False,
    description="填入此用户的 API Key；初始管理员使用本地 .env 的 BID_BOOTSTRAP_API_KEY。只填值，不加 Bearer。")


cookie_auth = APIKeyCookie(name=COOKIE_NAME, scheme_name="BrowserSession", auto_error=False,
    description="通过浏览器登录接口设置的 HttpOnly Cookie。Cookie 写操作还须携带与本站一致的 Origin。")


def authenticated_user(request: Request, db: DB, key: Annotated[str | None, Depends(key_header)],
                       cookie: Annotated[str | None, Depends(cookie_auth)]) -> User:
    user = None
    if key is not None:
        user = db.scalar(select(User).where(User.api_key_hash == sha256(key.encode())))
    elif cookie:
        session = db.scalar(select(WebSession).where(WebSession.token_hash == sha256(cookie.encode()),
                                                     WebSession.expires_at > utcnow()))
        if session:
            user = db.get(User, session.user_id)
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                same_origin(request)
    if user is None:
        raise HTTPException(401, "A valid API key or browser session is required")
    return user


CurrentUser = Annotated[User, Depends(authenticated_user)]
ProjectID = Annotated[str, Path(description="投标项目 ID，从创建项目接口取得。")]
RequirementID = Annotated[str, Path(description="逻辑要求 ID。多次修订仍属于同一要求。")]
TaskID = Annotated[str, Path(description="整改任务 ID，从登记问题或任务列表取得。")]
WriteKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128,
    description="本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。")]
