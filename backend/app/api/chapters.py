"""章节路由：章节列表、知识点、学生进度。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import select, or_, and_

from ..deps import CurrentUser, DBSession, resolve_config_class_id, require_role
from ..models import Chapter, ChapterProgress, KnowledgePoint, Material, QuestionBank
from ..services.enrollment import get_student_class_for_course
from ..services.agent_access import resolve_agent_for_exam, resolve_bank_class_ids, resolve_resource_class_ids_for_agent, apply_agent_content_scope, assert_agent_access, is_adopted_snapshot
from ..services.chapter_sync import (
    assert_teacher_can_manage_course,
    create_custom_chapters,
    reset_dynamic_course,
    C_LANG_COURSE_ID,
    requires_agent_scoped_chapters,
    uses_course_level_preset_chapters,
    agent_scoped_chapter_condition,
)

router = APIRouter(prefix="/chapters", tags=["chapters"])


class CustomChapterItem(BaseModel):
    title: str
    description: str = ""
    order_idx: int | None = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("章节标题不能为空")
        return v


class CustomChaptersIn(BaseModel):
    course_id: int
    agent_id: int | None = None
    chapters: list[CustomChapterItem]

    @field_validator("chapters")
    @classmethod
    def chapters_not_empty(cls, v: list[CustomChapterItem]) -> list[CustomChapterItem]:
        if not v:
            raise ValueError("请至少添加一个章节")
        if len(v) > 50:
            raise ValueError("单次最多创建 50 个章节")
        return v


@router.get("")
def list_chapters(
    _u: CurrentUser,
    db: DBSession,
    course_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
) -> list[dict]:
    q = select(Chapter).order_by(Chapter.order_idx, Chapter.id)
    if course_id is not None:
        q = q.where(Chapter.course_id == course_id)
    if course_id is not None and uses_course_level_preset_chapters(db, course_id, agent_id):
        q = q.where(Chapter.agent_id.is_(None))
    elif course_id is not None and requires_agent_scoped_chapters(db, course_id, agent_id):
        if agent_id is None:
            return []
        q = q.where(agent_scoped_chapter_condition(db, course_id, agent_id))
    rows = db.scalars(q).all()
    return [
        {
            "id": c.id, "course_id": c.course_id, "title": c.title,
            "order_idx": c.order_idx, "description": c.description,
        }
        for c in rows
    ]


@router.post("/custom", dependencies=[Depends(require_role("teacher", "admin"))])
def create_custom_chapters_api(payload: CustomChaptersIn, user: CurrentUser, db: DBSession) -> dict:
    """手动定义章节结构，之后可按章上传资料构建知识库。"""
    assert_teacher_can_manage_course(db, user, payload.course_id)
    rows = create_custom_chapters(
        db,
        payload.course_id,
        [c.model_dump() for c in payload.chapters],
        agent_id=payload.agent_id,
    )
    return {"ok": True, "count": len(rows), "chapters": rows}


@router.post("/reset-course", dependencies=[Depends(require_role("teacher", "admin"))])
def reset_course_chapters(
    user: CurrentUser,
    db: DBSession,
    course_id: int = Query(...),
    agent_id: int | None = Query(default=None),
) -> dict:
    """清空动态课程的章节与资料，便于重新识别章节结构。"""
    assert_teacher_can_manage_course(db, user, course_id)
    result = reset_dynamic_course(db, course_id, agent_id=agent_id, set_agent_planned=True)
    return {"ok": True, **result}


@router.get("/{chapter_id}")
def get_chapter(
    chapter_id: int,
    user: CurrentUser,
    db: DBSession,
    class_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
) -> dict:
    c = db.get(Chapter, chapter_id)
    if not c:
        raise HTTPException(404, "章节不存在")
    config_class_id: int | None = None
    if user.role == "student":
        config_class_id = get_student_class_for_course(db, user, c.course_id) or user.class_id
    elif class_id is not None:
        config_class_id = resolve_config_class_id(db, user, class_id, agent_id=agent_id)

    agent = None
    if config_class_id:
        agent = resolve_agent_for_exam(db, user, config_class_id, c.course_id, agent_id)
        kp_class_ids = resolve_bank_class_ids(db, agent, config_class_id)
        kp_q = select(KnowledgePoint).where(KnowledgePoint.chapter_id == chapter_id)
        if agent and is_adopted_snapshot(agent):
            kp_q = kp_q.where(or_(
                KnowledgePoint.agent_id == agent.id,
                KnowledgePoint.class_id.in_(kp_class_ids),
            ))
        else:
            kp_q = kp_q.where(KnowledgePoint.class_id.in_(kp_class_ids))
        kps = db.scalars(kp_q).all()
    else:
        kps = []
    allowed_classes = resolve_resource_class_ids_for_agent(
        db, user, class_id, agent_id=agent_id,
    )
    if agent_id and not agent:
        agent = assert_agent_access(db, user, agent_id)
    mq = select(Material).where(Material.chapter_id == chapter_id)
    mq = apply_agent_content_scope(Material, mq, agent, allowed_classes, db=db)
    if mq is None:
        materials = []
    else:
        materials = db.scalars(mq).all()
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
def all_progress(
    user: CurrentUser,
    db: DBSession,
    course_id: int | None = Query(default=None),
    agent_id: int | None = Query(default=None),
) -> list[dict]:
    q = select(ChapterProgress).where(ChapterProgress.user_id == user.id)
    if course_id is not None:
        ch_q = select(Chapter.id).where(Chapter.course_id == course_id)
        if uses_course_level_preset_chapters(db, course_id, agent_id):
            ch_q = ch_q.where(Chapter.agent_id.is_(None))
        elif requires_agent_scoped_chapters(db, course_id, agent_id):
            if agent_id is None:
                return []
            ch_q = ch_q.where(agent_scoped_chapter_condition(db, course_id, agent_id))
        chapter_ids = db.scalars(ch_q).all()
        if not chapter_ids:
            return []
        q = q.where(ChapterProgress.chapter_id.in_(chapter_ids))
    rows = db.scalars(q).all()
    return [{"chapter_id": r.chapter_id, "status": r.status, "last_exam_id": r.last_exam_id}
            for r in rows]
