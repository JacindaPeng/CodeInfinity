"""通用大模型对话（SSE 流式）。"""
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..deps import CurrentUser, DBSession, log_call
from ..services.llm_provider import get_provider

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatIn(BaseModel):
    messages: list[dict]  # [{"role":"user","content":"..."}]
    provider: str | None = None
    config_id: int | None = None


@router.post("/stream")
async def chat_stream(payload: ChatIn, user: CurrentUser, db: DBSession):
    provider = get_provider(payload.provider, payload.config_id)
    started = time.time()

    async def gen() -> AsyncGenerator[dict, None]:
        full = []
        try:
            async for token in provider.stream_chat(payload.messages):
                full.append(token)
                yield {"event": "message", "data": json.dumps({"text": token}, ensure_ascii=False)}
            yield {"event": "message", "data": "[DONE]"}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"text": f"LLM 调用失败: {e}"}, ensure_ascii=False)}
        finally:
            latency = int((time.time() - started) * 1000)
            log_call(
                db, endpoint="/api/chat/stream", user_id=user.id,
                req_summary=payload.messages[-1]["content"][:200] if payload.messages else "",
                resp_summary="".join(full)[:200],
                latency_ms=latency,
            )

    return EventSourceResponse(gen())
