"""智能体管理 + 课程问答 SSE。"""
import json
import time

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from ..deps import CurrentUser, DBSession, log_call, resolve_resource_class_ids
from ..models import Agent, CallLog
from ..services import recommend_service
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


def _agent_dict(a: Agent, db: DBSession | None = None) -> dict:
    course_name = ""
    if a.course_id and db:
        from ..models import Course
        c = db.get(Course, a.course_id)
        course_name = c.name if c else ""
    return {
        "id": a.id,
        "name": a.name,
        "intro": a.intro,
        "endpoint": a.endpoint,
        "course_id": a.course_id,
        "course_name": course_name,
        "slug": a.slug or "",
        "status": a.status or "active",
    }


@router.get("")
def list_agents(_u: CurrentUser, db: DBSession) -> list[dict]:
    rows = db.scalars(select(Agent).order_by(Agent.id)).all()
    return [_agent_dict(a, db) for a in rows]


@router.get("/course/history")
def course_ask_history(
    user: CurrentUser,
    db: DBSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=15, ge=1, le=50),
) -> dict:
    """当前用户的课程问答历史（来自调用日志）。"""
    base = select(CallLog).where(
        CallLog.user_id == user.id,
        CallLog.endpoint == "/api/agents/course/ask",
    )
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
def get_agent(agent_id: int, _u: CurrentUser, db: DBSession) -> dict:
    a = db.get(Agent, agent_id)
    if not a:
        from fastapi import HTTPException
        raise HTTPException(404, "智能体不存在")
    return _agent_dict(a, db)


class CourseAskIn(BaseModel):
    question: str
    chapter_id: int | None = None
    class_id: int | None = None
    history: list[dict] = []
    provider: str | None = None
    config_id: int | None = None
    attachments: list[AttachmentIn] = []


@router.post("/course/ask")
async def course_ask(payload: CourseAskIn, user: CurrentUser, db: DBSession):
    """课程问答 SSE：先发 recommend 事件，再流式回答。"""
    if user.role == "teacher" and not payload.class_id:
        raise HTTPException(400, "请选择班级")
    class_ids = resolve_resource_class_ids(db, user, payload.class_id)
    llm = get_provider(payload.provider, payload.config_id)
    has_attachments = bool(payload.attachments)
    effective_question = build_user_content_with_attachments(payload.question, payload.attachments)
    search_query = (
        build_attachment_search_query(payload.attachments, payload.question)
        if has_attachments else payload.question
    )
    hits = retrieve(search_query, chapter_id=payload.chapter_id, class_ids=class_ids)
    if has_attachments:
        recommendations = recommend_service.recommend_from_attachment(
            db, payload.attachments, class_ids, payload.chapter_id,
        )
    else:
        recommendations = recommend_service.recommend_from_hits(db, hits)
    rec_text = recommend_service.format_for_prompt(recommendations)
    _, stream = await rag_stream(
        effective_question, payload.history, payload.chapter_id,
        class_ids=class_ids, provider=llm,
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
            log_call(
                db, endpoint="/api/agents/course/ask", user_id=user.id,
                req_summary=_summary_with_attachments(payload.question, payload.attachments),
                resp_summary="".join(full)[:200],
                model_name=llm.model,
                answer_full="".join(full),
                attachments_json=_attachments_for_log(payload.attachments),
                latency_ms=latency,
            )

    return EventSourceResponse(gen())
