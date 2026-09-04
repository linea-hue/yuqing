from __future__ import annotations

from time import time

from .store import store


class AuthenticationError(PermissionError):
    pass


def actor_from_header(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("缺少 Bearer 登录令牌")
    token = authorization.split(" ", 1)[1].strip()
    actor = store.sessions.get(token)
    if not actor:
        raise AuthenticationError("登录令牌无效")
    if float(actor.get("expires_at", 0)) <= time():
        store.sessions.pop(token, None)
        raise AuthenticationError("登录令牌已过期，请重新登录")
    return actor


def require_role(authorization: str | None, *roles: str) -> dict:
    actor = actor_from_header(authorization)
    allowed = {role.upper() for role in roles}
    if actor["role"].upper() not in allowed:
        raise AuthenticationError("当前账号没有执行此操作的权限")
    return actor
