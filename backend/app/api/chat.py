"""通用大模型对话（SSE 流式）。"""
import json
import mimetypes
import time
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from ..deps import CurrentUser, DBSession, log_call, oauth2_scheme, user_from_access_token
from ..models import CallLog
from ..services.chat_file_service import parse_upload, resolve_chat_attachment
from ..services.llm_provider import get_provider
from ..services import speech_service

router = APIRouter(prefix="/chat", tags=["chat"])


class AttachmentIn(BaseModel):
    name: str
    text: str
    type: str = "document"
    file_id: str | None = None
    truncated: bool = False
    size: int | None = None


class ChatIn(BaseModel):
    messages: list[dict]  # [{"role":"user","content":"..."}]
    provider: str | None = None
    config_id: int | None = None
    attachments: list[AttachmentIn] = []


def _inject_attachments(messages: list[dict], attachments: list[AttachmentIn]) -> list[dict]:
    if not attachments:
        return messages
    msgs = [dict(m) for m in messages]
    if not msgs or msgs[-1].get("role") != "user":
        return msgs
    msgs[-1]["content"] = build_user_content_with_attachments(
        msgs[-1].get("content") or "", attachments
    )
    return msgs


def build_user_content_with_attachments(text: str, attachments: list[AttachmentIn]) -> str:
    if not attachments:
        return text
    blocks = [f"【附件：{a.name}】\n{a.text}" for a in attachments]
    combined = "\n\n".join(blocks)
    user_text = text.strip()
    if user_text:
        return f"{user_text}\n\n---\n以下为用户上传的附件内容：\n\n{combined}"
    return f"请根据以下用户上传的附件内容作答：\n\n{combined}"


def build_attachment_search_query(attachments: list[AttachmentIn], question: str = "") -> str:
    """用附件正文驱动 RAG 检索，避免仅用「考点/推荐资源」等元问题词检索到无关教材片段。"""
    parts = [a.text.strip() for a in attachments if a.text and a.text.strip()]
    if not parts:
        return question.strip()
    combined = "\n".join(parts)
    q = question.strip()
    # 附件优先，问题补充意图
    body = combined[:12000]
    return f"{body}\n\n{q}" if q else body


def _summary_with_attachments(text: str, attachments: list[AttachmentIn]) -> str:
    names = "、".join(a.name for a in attachments)
    base = text.strip() or "（基于附件提问）"
    if attachments:
        return f"{base} [附件: {names}]"
    return base


def _attachments_for_log(attachments: list[AttachmentIn]) -> str:
    if not attachments:
        return ""
    payload = [
        {
            "name": a.name,
            "type": a.type,
            "text": a.text[:50000],
            "file_id": a.file_id or "",
            "truncated": a.truncated,
            "size": a.size,
        }
        for a in attachments
    ]
    return json.dumps(payload, ensure_ascii=False)


def _parse_attachments_json(raw: str) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


@router.post("/parse-file")
async def chat_parse_file(user: CurrentUser, file: UploadFile = File(...)) -> dict:
    """上传并解析对话附件，返回提取的文本。"""
    return await parse_upload(file, user.id)


@router.get("/voice-status")
def chat_voice_status(_user: CurrentUser) -> dict:
    """语音输入能力：本地 Whisper + ffmpeg 可用时走录音识别。"""
    has_whisper = speech_service.whisper_available()
    has_ffmpeg = speech_service.ffmpeg_available()
    ok = speech_service.speech_available()
    if ok:
        hint = "录音识别（本地）"
    elif has_whisper and not has_ffmpeg:
        hint = "已安装 Whisper，但未找到 ffmpeg。请安装后重启后端，或设置 FFMPEG_PATH"
    elif not has_whisper:
        hint = "浏览器语音识别（需 Chrome/Edge 且网络可用）"
    else:
        hint = "语音输入不可用"
    return {
        "available": ok,
        "whisper": has_whisper,
        "ffmpeg": has_ffmpeg,
        "engine": "whisper" if ok else "webspeech",
        "hint": hint,
    }


@router.post("/transcribe")
async def chat_transcribe(user: CurrentUser, file: UploadFile = File(...)) -> dict:
    """上传录音并由 Whisper 转写为文本。"""
    _ = user
    if not speech_service.speech_available():
        if speech_service.whisper_available() and not speech_service.ffmpeg_available():
            raise HTTPException(
                503,
                "未找到 ffmpeg。请执行 winget install Gyan.FFmpeg 后重启后端，"
                "或在 .env 设置 FFMPEG_PATH",
            )
        raise HTTPException(
            503,
            "未安装 Whisper。请执行 pip install -r requirements_video.txt，或改用 Chrome 浏览器语音输入",
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "录音为空")
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(400, "录音过大，请缩短后重试")
    try:
        text = await speech_service.transcribe_upload(raw, file.filename or "voice.webm")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    except Exception as e:
        raise HTTPException(500, f"语音识别失败: {e}") from e
    return {"text": text}


@router.get("/attachments/{file_id}")
def get_chat_attachment(
    file_id: str,
    db: DBSession,
    header_token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    token: str | None = Query(default=None),
) -> FileResponse:
    """下载/预览已上传的对话附件（支持 Header 或 ?token= 鉴权）。"""
    user = user_from_access_token(token or header_token, db)
    path = resolve_chat_attachment(user.id, file_id)
    if not path or not path.is_file():
        raise HTTPException(404, "附件不存在或已过期")
    display_name = path.name.split("__", 1)[1] if "__" in path.name else path.name
    media_type, _ = mimetypes.guess_type(display_name)
    inline = media_type in ("application/pdf",) or (media_type or "").startswith("image/")
    return FileResponse(
        path,
        filename=display_name,
        media_type=media_type or "application/octet-stream",
        content_disposition_type="inline" if inline else "attachment",
    )


@router.get("/history")
def chat_history(
    user: CurrentUser,
    db: DBSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=15, ge=1, le=50),
) -> dict:
    """当前用户的大模型对话历史（来自调用日志）。"""
    base = select(CallLog).where(
        CallLog.user_id == user.id,
        CallLog.endpoint == "/api/chat/stream",
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


@router.post("/stream")
async def chat_stream(payload: ChatIn, user: CurrentUser, db: DBSession):
    provider = get_provider(payload.provider, payload.config_id)
    messages = _inject_attachments(payload.messages, payload.attachments)
    started = time.time()
    raw_question = payload.messages[-1]["content"] if payload.messages else ""

    async def gen() -> AsyncGenerator[dict, None]:
        full = []
        try:
            async for token in provider.stream_chat(messages):
                full.append(token)
                yield {"event": "message", "data": json.dumps({"text": token}, ensure_ascii=False)}
            yield {"event": "message", "data": "[DONE]"}
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"text": f"LLM 调用失败: {e}"}, ensure_ascii=False)}
        finally:
            latency = int((time.time() - started) * 1000)
            log_call(
                db, endpoint="/api/chat/stream", user_id=user.id,
                req_summary=_summary_with_attachments(raw_question, payload.attachments),
                resp_summary="".join(full)[:200],
                model_name=provider.model,
                answer_full="".join(full),
                attachments_json=_attachments_for_log(payload.attachments),
                latency_ms=latency,
            )

    return EventSourceResponse(gen())
