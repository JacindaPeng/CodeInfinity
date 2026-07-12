"""资源推荐接口。"""
from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import CurrentUser, DBSession, resolve_resource_class_ids
from ..services import recommend_service

router = APIRouter(prefix="/recommend", tags=["recommend"])


class RecommendIn(BaseModel):
    question: str
    chapter_id: int | None = None
    k: int = 5


@router.post("")
def recommend(payload: RecommendIn, user: CurrentUser, db: DBSession) -> list[dict]:
    class_ids = resolve_resource_class_ids(db, user)
    return recommend_service.recommend_by_question(
        db, payload.question, payload.chapter_id, payload.k, class_ids=class_ids
    )
