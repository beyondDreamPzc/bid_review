"""Cookie 认证的同源写入检查；API Key 客户端不依赖浏览器环境。"""
from fastapi import HTTPException, Request

COOKIE_NAME = "bid_web_session"


def same_origin(request: Request, required: bool = True):
    origin = request.headers.get("origin")
    expected = str(request.base_url).rstrip("/")
    if (required and not origin) or (origin and origin != expected):
        raise HTTPException(403, "Browser writes require the same Origin as this service")
