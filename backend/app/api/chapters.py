"""章节路由：章节列表、知识点、学生进度。"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..deps import CurrentUser, DBSession
from ..models import Chapter, ChapterProgress, KnowledgePoint, Material

router = APIRouter(prefix="/chapters", tags=["chapters"])


@router.get("")
def list_chapters(_u: CurrentUser, db: DBSession) -> list[dict]:
    rows = db.scalars(
        select(Chapter).order_by(Chapter.order_idx, Chapter.id)
    ).all()
    return [
        {
            "id": c.id, "course_id": c.course_id, "title": c.title,
            "order_idx": c.order_idx, "description": c.description,
        }
        for c in rows
    ]


@router.get("/{chapter_id}")
def get_chapter(chapter_id: int, _u: CurrentUser, db: DBSession) -> dict:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")
    kps = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.chapter_id == chapter_id)
    ).all()
    materials = db.scalars(
        select(Material).where(Material.chapter_id == chapter_id)
    ).all()
    return {
        "id": c.id, "title": c.title, "description": c.description,
        "knowledge_points": [{"id": k.id, "name": k.name} for k in kps],
        "materials": [
            {"id": m.id, "type": m.type, "title": m.title}
            for m in materials
        ],
    }


@router.get("/{chapter_id}/progress")
def chapter_progress(chapter_id: int, user: CurrentUser, db: DBSession) -> dict:
    p = db.scalar(
        select(ChapterProgress).where(
            ChapterProgress.user_id == user.id,
            ChapterProgress.chapter_id == chapter_id,
        )
    )
    if not p:
        return {"status": "未完成", "last_exam_id": None}
    return {"status": p.status, "last_exam_id": p.last_exam_id}


@router.get("/progress/all")
def all_progress(user: CurrentUser, db: DBSession) -> list[dict]:
    rows = db.scalars(
        select(ChapterProgress).where(ChapterProgress.user_id == user.id)
    ).all()
    return [{"chapter_id": r.chapter_id, "status": r.status, "last_exam_id": r.last_exam_id}
            for r in rows]
