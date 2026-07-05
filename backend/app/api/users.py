"""用户路由。"""
from fastapi import APIRouter

from ..deps import CurrentUser
from ..schemas import UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return user
