"""用户路由。"""
from fastapi import APIRouter

from ..deps import CurrentUser, DBSession
from ..schemas import UserOut, build_user_out

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser, db: DBSession) -> UserOut:
    return build_user_out(user, db)
