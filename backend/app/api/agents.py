"""智能体管理 + 课程问答 SSE。"""
import json
import time

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from ..deps import CurrentUser, DBSession, log_call
from ..models import Agent
from ..services import recommend_service
from ..services.rag_service import rag_stream

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
def list_agents(_u: CurrentUser, db: DBSession) -> list[dict]:
    rows = db.scalars(select(Agent).order_by(Agent.id)).all()
    return [
        {"id": a.id, "name": a.name, "intro": a.intro, "endpoint": a.endpoint}
        for a in rows
    ]


@router.get("/{agent_id}")
def get_agent(agent_id: int, _u: CurrentUser, db: DBSession) -> dict:
    a = db.get(Agent, agent_id)
    if not a:
        from fastapi import HTTPException
        raise HTTPException(404, "智能体不存在")
    return {"id": a.id, "name": a.name, "intro": a.intro, "endpoint": a.endpoint}


class CourseAskIn(BaseModel):
    question: str
    chapter_id: int | None = None
    history: list[dict] = []


@router.post("/course/ask")
async def course_ask(payload: CourseAskIn, user: CurrentUser, db: DBSession):
    """课程问答 SSE：先发 recommend 事件，再流式回答。"""
    hits, stream = await rag_stream(
        payload.question, payload.history, payload.chapter_id
    )
    recommendations = recommend_service.recommend_from_hits(db, hits)
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
                req_summary=payload.question[:200],
                resp_summary="".join(full)[:200],
                latency_ms=latency,
            )

    return EventSourceResponse(gen())
