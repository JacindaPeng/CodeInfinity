"""智能体管理 + 课程问答 SSE。"""
import json
import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from ..deps import CurrentUser, DBSession, log_call
from ..models import Agent, CallLog, Chapter, Course, User
from ..services import recommend_service
from ..services.agent_access import (
    assert_agent_access,
    can_teacher_manage_agent_content,
    get_bound_class_ids,
    get_shared_content_class_ids,
    get_teacher_agent_bound_classes,
    get_visible_agent_ids,
    resolve_retrieval_agent_id,
    resolve_retrieval_class_ids,
)
from ..services.chapter_sync import uses_course_level_preset_chapters
from ..services.llm_provider import get_provider
from ..services.rag_service import rag_stream, retrieve
from .chat import (
    AttachmentIn,
    _attachments_for_log,
    _parse_attachments_json,
    _summary_with_attachments,
    build_attachment_search_query,
    build_user_content_with_attachments,
)

router = APIRouter(prefix="/agents", tags=["agents"])


def _agent_dict(a: Agent, db: DBSession | None = None, user: User | None = None) -> dict:
    course_name = ""
    if a.course_id and db:
        c = db.get(Course, a.course_id)
        course_name = c.name if c else ""
    owner_name = ""
    if a.owner_id and db:
        u = db.get(User, a.owner_id)
        owner_name = (u.display_name or u.username) if u else ""
    bound_class_ids = get_bound_class_ids(db, a.id) if db else []
    if db and user and user.role == "teacher":
        managed_bound = get_teacher_agent_bound_classes(db, user, a.id)
        if managed_bound:
            bound_class_ids = managed_bound
    shared_content_class_ids = get_shared_content_class_ids(db, a) if db else []
    is_owner = user is not None and a.owner_id == user.id
    can_manage_content = bool(
        user
        and (
            user.role == "admin"
            or is_owner
            or (user.role == "teacher" and can_teacher_manage_agent_content(db, user, a.id))
        )
    )
    return {
        "id": a.id,
        "name": a.name,
        "intro": a.intro,
        "endpoint": a.endpoint,
        "course_id": a.course_id,
        "course_name": course_name,
        "slug": a.slug or "",
        "status": a.status or "active",
        "owner_id": a.owner_id,
        "owner_name": owner_name,
        "source_agent_id": a.source_agent_id,
        "is_adopted": bool(a.source_agent_id),
        "is_shared": bool(a.is_shared),
        "is_owner": is_owner,
        "can_manage_content": can_manage_content,
        "bound_class_ids": bound_class_ids,
        "shared_content_class_ids": shared_content_class_ids,
        "uses_preset_chapters": bool(
            db and a.course_id and uses_course_level_preset_chapters(db, a.course_id, a.id)
        ),
    }


@router.get("")
def list_agents(user: CurrentUser, db: DBSession) -> list[dict]:
    if user.role == "admin":
        rows = db.scalars(select(Agent).order_by(Agent.id)).all()
        return [_agent_dict(a, db, user) for a in rows]
    visible = get_visible_agent_ids(db, user)
    if not visible:
        return []
    rows = db.scalars(select(Agent).where(Agent.id.in_(visible)).order_by(Agent.id)).all()
    # 「进入」列表仅展示已上线：筹备中的空壳只在「我的管理」出现
    if user.role in ("student", "teacher"):
        rows = [a for a in rows if a.status == "active"]
    return [_agent_dict(a, db, user) for a in rows]


@router.get("/course/history")
def course_ask_history(
    user: CurrentUser,
    db: DBSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=15, ge=1, le=50),
    agent_id: int | None = Query(default=None),
) -> dict:
    """当前用户的课程问答历史（来自调用日志）。"""
    base = select(CallLog).where(
        CallLog.user_id == user.id,
        CallLog.endpoint == "/api/agents/course/ask",
    )
    if agent_id is not None:
        base = base.where(CallLog.req_summary.like(f"[agent:{agent_id}]%"))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(CallLog.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": r.id,
                "question": r.req_summary,
                "answer": r.answer_full or r.resp_summary,
                "has_full_answer": bool(r.answer_full),
                "model_name": r.model_name or "",
                "attachments": _parse_attachments_json(r.attachments_json),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/{agent_id}")
def get_agent(agent_id: int, user: CurrentUser, db: DBSession) -> dict:
    if user.role == "admin":
        a = db.get(Agent, agent_id)
        if not a:
            raise HTTPException(404, "智能体不存在")
        return _agent_dict(a, db, user)
    a = assert_agent_access(db, user, agent_id)
    return _agent_dict(a, db, user)


class CourseAskIn(BaseModel):
    question: str
    chapter_id: int | None = None
    class_id: int | None = None
    agent_id: int | None = None
    history: list[dict] = []
    provider: str | None = None
    config_id: int | None = None
    attachments: list[AttachmentIn] = []


def _resolve_course_context(db: DBSession, payload: CourseAskIn) -> tuple[int | None, str | None]:
    """根据 agent_id 解析 course_id 与 slug；校验 chapter 归属课程。"""
    course_id: int | None = None
    agent_slug: str | None = None
    if payload.agent_id:
        agent = db.get(Agent, payload.agent_id)
        if not agent:
            raise HTTPException(404, "智能体不存在")
        if agent.status != "active":
            raise HTTPException(400, "该课程智能体尚未上线，请从课程智能体列表选择已上线课程")
        course_id = agent.course_id
        agent_slug = agent.slug or None
    if payload.chapter_id and course_id:
        ch = db.get(Chapter, payload.chapter_id)
        if ch and ch.course_id != course_id:
            raise HTTPException(400, "所选章节不属于当前课程")
    return course_id, agent_slug


@router.post("/course/ask")
async def course_ask(payload: CourseAskIn, user: CurrentUser, db: DBSession):
    """课程问答 SSE：先发 recommend 事件，再流式回答。"""
    if user.role == "teacher" and not payload.class_id:
        raise HTTPException(400, "请选择班级")
    course_id, agent_slug = _resolve_course_context(db, payload)
    agent_obj: Agent | None = None
    if payload.agent_id:
        agent_obj = assert_agent_access(db, user, payload.agent_id)
    retrieval_class_ids = resolve_retrieval_class_ids(db, agent_obj, user, payload.class_id)
    retrieval_agent_id = resolve_retrieval_agent_id(db, agent_obj)
    if retrieval_class_ids is not None and not retrieval_class_ids and not retrieval_agent_id:
        raise HTTPException(400, "无法确定资料检索班级范围")
    llm = get_provider(payload.provider, payload.config_id)
    has_attachments = bool(payload.attachments)
    effective_question = build_user_content_with_attachments(payload.question, payload.attachments)
    search_query = (
        build_attachment_search_query(payload.attachments, payload.question)
        if has_attachments else payload.question
    )
    hits = retrieve(
        search_query, chapter_id=payload.chapter_id, class_ids=retrieval_class_ids,
        course_id=course_id, agent_id=retrieval_agent_id,
    )
    if has_attachments:
        recommendations = recommend_service.recommend_from_attachment(
            db, payload.attachments, retrieval_class_ids, payload.chapter_id,
            course_id=course_id, agent_id=retrieval_agent_id,
            question=payload.question,
        )
    else:
        recommendations = recommend_service.recommend_from_hits(db, hits)
        recommendations = recommend_service.ensure_video_recommendations(
            db, recommendations, search_query,
            chapter_id=payload.chapter_id,
            class_ids=retrieval_class_ids,
            course_id=course_id,
            agent_id=retrieval_agent_id,
            hits=hits,
        )
        recommendations = recommend_service.filter_relevant_recommendations(
            recommendations, hits, search_query,
        )
    rec_text = recommend_service.format_for_prompt(recommendations)
    _, stream = await rag_stream(
        effective_question, payload.history, payload.chapter_id,
        class_ids=retrieval_class_ids, course_id=course_id, agent_slug=agent_slug,
        provider=llm,
        search_query=search_query,
        has_attachments=has_attachments,
        recommendations_text=rec_text,
        precomputed_hits=hits,
    )
    started = time.time()

    async def gen():
        full: list[str] = []
        try:
            # 先推送推荐资源
            yield {
                "event": "recommend",
                "data": json.dumps({"recommendations": recommendations}, ensure_ascii=False),
            }
            # 流式回答
            async for token in stream:
                full.append(token)
                yield {"event": "message", "data": json.dumps({"text": token}, ensure_ascii=False)}
            yield {"event": "message", "data": "[DONE]"}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"text": f"LLM 调用失败: {e}"}, ensure_ascii=False)}
        finally:
            latency = int((time.time() - started) * 1000)
            summary = _summary_with_attachments(payload.question, payload.attachments)
            if payload.agent_id:
                summary = f"[agent:{payload.agent_id}] {summary}"
            log_call(
                db, endpoint="/api/agents/course/ask", user_id=user.id,
                req_summary=summary,
                resp_summary="".join(full)[:200],
                model_name=llm.model,
                answer_full="".join(full),
                attachments_json=_attachments_for_log(payload.attachments),
                latency_ms=latency,
            )

    return EventSourceResponse(gen())
