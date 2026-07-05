"""依赖注入：当前用户、DB 会话、调用日志写入。"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import CallLog, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc).timestamp() + settings.jwt_expire_minutes * 60
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未认证或凭证已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise cred_exc
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = int(payload.get("sub", "0"))
    except JWTError:
        raise cred_exc
    user = db.get(User, user_id)
    if not user:
        raise cred_exc
    return user


def require_role(*roles: str):
    """角色守卫：require_role('teacher','admin')。"""
    def _dep(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return user
    return _dep


def log_call(
    db: Session,
    endpoint: str,
    user_id: int | None = None,
    req_summary: str = "",
    resp_summary: str = "",
    tokens: int = 0,
    latency_ms: int = 0,
) -> None:
    db.add(CallLog(
        user_id=user_id, endpoint=endpoint,
        req_summary=req_summary[:500], resp_summary=resp_summary[:500],
        tokens=tokens, latency_ms=latency_ms,
    ))
    db.commit()


CurrentUser = Annotated[User, Depends(get_current_user)]
DBSession = Annotated[Session, Depends(get_db)]
