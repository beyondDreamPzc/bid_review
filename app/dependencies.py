"""API 身份与数据库依赖，文档接口和业务接口共用同一认证入口。"""
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Path
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.storage import sha256

DB = Annotated[Session, Depends(get_db)]
key_header = APIKeyHeader(name="X-API-Key", scheme_name="ApiKeyAuth", auto_error=False,
    description="填入此用户的 API Key；初始管理员使用本地 .env 的 BID_BOOTSTRAP_API_KEY。只填值，不加 Bearer。")


def authenticated_user(db: DB, key: Annotated[str | None, Depends(key_header)]) -> User:
    user = db.scalar(select(User).where(User.api_key_hash == sha256(key.encode()))) if key else None
    if user is None:
        raise HTTPException(401, "A valid X-API-Key is required")
    return user


CurrentUser = Annotated[User, Depends(authenticated_user)]
ProjectID = Annotated[str, Path(description="投标项目 ID，从创建项目接口取得。")]
RequirementID = Annotated[str, Path(description="逻辑要求 ID。多次修订仍属于同一要求。")]
TaskID = Annotated[str, Path(description="整改任务 ID，从登记问题或任务列表取得。")]
WriteKey = Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128,
    description="本次业务操作的幂等键，建议 UUID。重试保持键和请求体不变；新操作换新键。")]
